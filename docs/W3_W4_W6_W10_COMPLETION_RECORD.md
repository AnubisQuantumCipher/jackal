# JACKAL juggernaut — W3 / W4 / W6 / W10 completion record

**Date:** 2026-08-19
**Branch:** `feat/domain-pack-protocol`
**Engine source digest at close:** `jackal_calc.anb` =
`f579b6f59bc024d24914487b0cd0f18ea43dea1be52708a05a66dc885d80bb4e`
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

Guard: `tools/lcm_differential_gate.py`, a **39**-case frozen boundary corpus (10
rows exceeding `i64`; `len(CORPUS)` read from the file, and matching the
`cases=39 overflow_rows=10` the gate itself prints below — an earlier draft of
this line said 40, which was a miscount) that
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
{"pack_count":3,"operation_count":5,"status":"accepted",
 "anubis_execution_status":"NOT_EXECUTED","assurance_status":"NOT_MINTED", ...}
```

(`operation_count` was 4 when this record was first written and is 5 since
`decision.matrix.rank.v2` was registered — see §2. The line above was re-observed
from a fresh run on this machine, not edited to match.)

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

Two operations. `decision.matrix.rank.v1` -> `decision-rank` selects argmax/argmin
of caller-declared integer scores under a caller-declared criterion and records
the margin to the runner-up. `decision.matrix.rank.v2` -> `decision-rank-v2`
additionally requires a declared unit from a closed vocabulary and is documented
in "Closing the blocklist gap" below; v1 is retained byte-identical. Observed for
v1:

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
substring blocklist of 20 words. A blocklist is inherently incomplete. Measured
against the shipped engine, one word per row:

```
decision-rank d1 optimal          min alpha 120 beta 90  ->  selected=beta   (ACCEPTED)
decision-rank d1 ideal            min alpha 120 beta 90  ->  selected=beta   (ACCEPTED)
decision-rank d1 b3st             min alpha 120 beta 90  ->  selected=beta   (ACCEPTED)
decision-rank d1 best             min alpha 120 beta 90  ->  decision-value-judgment
decision-rank d1 preference_score min alpha 120 beta 90  ->  decision-value-judgment
```

An earlier draft of this paragraph listed `preference_score` among the words that
pass. It does not — it refuses, because `preference` is on the list. The
correction matters more than the word: the sentence had been written from
plausible reasoning about a blocklist rather than from running it, which is the
same defect class as the W6 overstatement recorded in §5. `optimal`, `ideal` and
`b3st` do pass, and were observed passing. The screen raises the cost of
laundering a value judgment; it does not close it. Closing it properly needs a
declared unit or measurement provenance on the criterion — which is what
`decision.matrix.rank.v2` below now does, additively, for callers who opt into it.

### Closing the blocklist gap — `decision.matrix.rank.v2`

`decision.matrix.rank.v2` -> `decision-rank-v2` takes the criterion PLUS a
declared unit and refuses any unit outside a closed vocabulary. The vocabulary is
not invented here: it is exactly the 66 canonical unit ids of the pinned
`release/claim/unit_registry_v1.json` (`jackal-unit-registry-v1`) minus `one`, the
dimensionless identity, which is excluded because declaring it says nothing about
what the numbers measure. Reusing that registry rather than writing a second unit
list is deliberate; the mechanism that keeps engine, checker and registry from
drifting is `DecisionUnitVocabularyTest`, which re-derives the set from the
registry file and probes the live engine for every member.

v1 is retained byte-identical and still accepts `most_elegant`. Narrowing a
shipped operation's accepted inputs would break its callers, so v2 is the closed
lane and v1's gap is asserted as a gap
(`test_known_gap_substring_blocklist_misses_optimal`).

Observed, on the engine at the digest recorded in the appendix:

```
$ decision-rank-v2 d_v2 latency_ms   ms          min alpha 120 beta 90
status=exact selected=beta margin=30 unit=ms
consequence=decision-boundary note=the-declared-criterion-and-unit-remain-the-callers-a-declared-unit-is-not-a-measurement
decision-cert={"claim":{...,"unit":"ms"},"kind":"decision-rank-v2","schema":"jackal-decision-cert-v2","witness":{}}

$ decision-rank-v2 d_v2 most_elegant elegance    max alpha 1 beta 2  ->  decision-unit-unknown
$ decision-rank-v2 d_v2 most_elegant ""          max alpha 1 beta 2  ->  decision-unit-missing
$ decision-rank-v2 d_v2 most_elegant             max alpha 1 beta 2  ->  pack-request-arity
$ decision-rank-v2 d_v2 b3st         elegance    max alpha 1 beta 2  ->  decision-unit-unknown
$ decision-rank-v2 d_v2 optimal_score one        max alpha 1 beta 2  ->  decision-unit-unknown
$ decision-rank-v2 d_v2 latency_ms   millisecond min alpha 120 beta 90 -> decision-unit-unknown
$ decision-rank-v2 d_v2 latency_ms   Ms          min alpha 120 beta 90 -> decision-unit-unknown
$ decision-rank-v2 d_v2 best_score   ms          min alpha 120 beta 90 -> decision-value-judgment
$ decision-rank    d_v1 most_elegant             max alpha 1 beta 2  ->  selected=beta (ACCEPTED, v1 unchanged)
```

The last two rows are the ones that matter. `best_score ms` shows the v1 word list
is retained as a *second* gate rather than replaced; `decision-rank` on
`most_elegant` shows v1's surface was not narrowed. Aliases (`millisecond`) and
case variants (`Ms`) are refused because the registry confines aliases to input
canonicalisation and because `mW` and `MW` differ by 10^6.

**What v2 does not close, stated rather than hidden.** A caller who declares an
admissible unit and names the criterion however they like is admitted:
`most_elegant` in `ms` ranks. No checker in this protocol can tell that a number
labelled `ms` is not a duration. That residual is asserted as a test
(`test_known_residual_v2_cannot_detect_a_mislabelled_criterion`) and as a manifest
nonclaim (`a_declared_unit_is_not_a_measurement`), not left as folklore.

The evidence contract was NOT widened to a new evidence kind: v2 reuses
`decision-cert` with a second admissible response schema under the same single
checker identity, so the consequence-ceiling matrix in §1 is unchanged (still 3
kinds, 12 cells) and `tests/cross_pack_non_laundering_test.py` passes without
edits.

**Arity encoding, a deliberate judgement call.** `decision-rank` is variadic
(7..15 operation arguments) but the protocol's `argument_schema` has no notion of
optional positions and the verifier requires
`len(argument_schema) == resources.max_arguments`. The manifest therefore declares
`max_arguments = 15` with 15 enumerated positions. Declaring the minimum instead
would set a resource bound the engine legitimately exceeds, which is strictly
worse. Growing the protocol an explicit min/max arity is the correct long-term
fix and was **not** done here, because it is a schema change. `decision-rank-v2`
follows the same encoding one slot wider: 8..16 operation arguments, declared as
`max_arguments = 16` with 16 enumerated positions, the extra one being `unit`.

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

### Superseded by the plugin-surface exposure (same branch, later commit)

The three transcripts above were observed when `plugin/hermes/tools.json`
declared 34 tools and **none** of W6's pack operations was reachable through the
plugin: a `grep` of `plugin/hermes/tools.json`, `plugin/hermes/server.py` and
`.agents/plugins/marketplace.json` for `test.exists|claim.cites|decision.rank|
pack.route|domain.pack` returned zero matches. W6's stated purpose is to carry
the assurance discipline past mathematics, and it could not do that while no
agent could call it. The four operations are now exposed as
`jackal_test_exists`, `jackal_claim_cites_test`, `jackal_decision_rank` and
`jackal_decision_rank_v2`, so the counts above read as history, not as current
state. Currently observed:

```
$ python3 tools/profile_verify.py
profile=core   tools=3  digest=52be7204... OK
profile=formal tools=13 digest=b4545486... OK
profile=full   tools=38 digest=64385db7... OK
profile_verification=verified tools_declared=38 nesting=core<=formal<=full OK

$ python3 -m unittest tests.profile_contract_test
Ran 29 tests — OK        case_census positive=12 refusal=16
```

`core` stays at exactly 3 and `formal` at 13. `tools/profile_verify.py` hard-
refuses any other core arity (`CORE_TOOL_COUNT = 3` → `core-arity`), and `core`'s
own description excludes bare producers — which is what all four pack lanes are,
`informational` consequence ceiling or not: they return a value and a status
directly, with no bundle, no route trace and no independent replay path.
`formal`'s exclusion clause now names them: their status is `structural-exact`
or `exact`, their checkers are ordinary Python recomputation with no Lean
checker and no theorem id, and admitting them would render a structural or
arithmetic fact as a formal one.

`tests/profile_contract_test.py` now derives the expected count from
`tools.json` instead of retyping it, and asserts that every operation in
`domain_packs/registry_v1.json` is named by exactly one tool on `full`
(`core.exact.mod_pow.v1` exempted by name: it routes to the `mod-pow` engine
command `jackal_mod_pow` already exposes). That assertion, not the JSON edit, is
the fix — it is what makes this omission recur loudly instead of silently. The
same reachability check is mechanised in the CI inventory lock.

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

`tools/eval_v2_gate.py` makes that unmeasurability a **verdict rather than a
remembered caveat**: it is three-valued (`EVAL_V2_GATE_PASS` exit 0,
`EVAL_V2_GATE_FAIL` exit 1, `EVAL_V2_GATE_NOT_MEASURABLE` exit 3, usage error 2)
and reports requirement 1 as NOT_MEASURABLE for four distinct named reasons,
never as satisfied:

- `reason=forced-mode-verifier-use-by-construction` on a forced receipt, where
  `metrics.py` reads `verifier_use_rate` `1.000000`. That 1.0 is the harness
  describing itself, not an agent choosing to verify.
- `reason=no-transcript-supplied` on an autonomous receipt with
  `transcript_path=None`, where `metrics.py` reads `0.000000`. That zero is an
  absent transcript, not a model declining to verify. Reporting either number as
  the requirement would be a vacuous metric of exactly the kind the two bullets
  above refuse.
- `reason=profile-identity-absent`, which fires **even on a receipt that does
  carry a transcript**, because `evals/v2/protocol.md` scopes requirement 1 to
  "the `autonomous` mode at the profile a live agent would actually receive", and
  its "Row identity" section states that "A row missing an identity field is not
  aggregated" while listing profile identity and `profile_digest_sha256` among
  the required fields.
- `reason=profile-identity-mismatch` when a receipt names a profile whose digest
  does not match the shipped one.

Both profile reasons are **observed firing**, not merely present in the source:
`python3 -m unittest tests.eval_v2_gate_test.Requirement1NotMeasurable -v` ->
`Ran 7 tests ... OK`, including `test_missing_profile_identity_is_not_measurable`
and `test_wrong_profile_digest_is_not_measurable`, which drive synthetic
autonomous receipts that DO carry `transcript_path`. The accurate scope limit is
narrower: what has never been observed is either reason on a receipt from a
**live model session**, because no such receipt exists. `runner.py` emits no
profile identity at all — `grep -cE 'profile_id|profile_digest_sha256' evals/v2/runner.py`
returns `0` — so it cannot produce a row the protocol would aggregate.

(An earlier draft of this section called the profile reason "source-verified, not
observed firing". That understated the evidence and was corrected on the report
of the agent that wrote the gate, after re-running the test here. Understating
evidence is a smaller sin than overstating it and still worth fixing, because a
later reader deciding whether to trust the gate would have been told the code
path was unexercised when it is covered by two passing tests.)

So closing requirement 1 needs a live transcript **and** a producer change to
`runner.py` so rows carry a profile identity. `runner.py` was **not** patched.

Reproduced on this machine, exact bytes of this branch:

```
$ python3 evals/v2/runner.py --mode forced      --out /tmp/dc_forced.json
$ python3 evals/v2/runner.py --mode autonomous  --out /tmp/dc_auto.json
$ python3 tools/eval_v2_gate.py --results /tmp/dc_forced.json --results /tmp/dc_auto.json
req2 ... verdict=PASS   silent_downgrade_count = 0  forced, rows=25
                        silent_downgrade_count = 0  autonomous, rows=25
req3 ... verdict=PASS   profile_verify exit=0, tools_declared=34
EVAL_V2_GATE_NOT_MEASURABLE exit=3
EVAL_V2_GATE_NOT_MEASURABLE is not a pass: exit 3
```

Re-observed after the pack lanes were exposed on the plugin surface (same
commands, same branch, `tools/eval_v2_gate.py` reads the count rather than
asserting one, so req3 is unaffected by the surface growth):

```
req2 ... verdict=PASS   silent_downgrade_count = 0  forced, rows=25
                        silent_downgrade_count = 0  autonomous, rows=25
req3 ... verdict=PASS   profile_verify exit=0, tools_declared=38
EVAL_V2_GATE_NOT_MEASURABLE exit=3
EVAL_V2_GATE_NOT_MEASURABLE is not a pass: exit 3
```

---

## 5. Honest status against the plan

| workstream | state | evidence |
|---|---|---|
| engine `lcm` defect | **closed** | before/after outputs + differential gate |
| W4 protocol + evidence contracts | **closed** | verifier accepts 3 packs / 4 ops; ceiling matrix; archival fix |
| W6 programming pack — behaviour | **closed** | route byte-parity + soundness refusals + independent checker + manifest nonclaims |
| W6 decision pack — behaviour | **closed** | route byte-parity + 5 refusal paths + independent checker |
| W6 — agent reachability through the plugin | **was silently OPEN behind every green gate; closed in this wave** | all four operations exposed as plugin tools (34 -> 38); driven end-to-end through `plugin/hermes/jackal_hermes call`; `tests/profile_contract_test.py::test_positive_every_pack_operation_is_reachable_on_full` + the CI inventory lock make a future omission a refusal |
| W6 pack surface inside the shipped v1.7.2 package | **NOT DONE** | `release/build_package_v172.sh` ships neither `domain_packs/` nor the two pack checkers, so the four lanes refuse `pack-surface-absent` inside the package (observed) while the other 34 keep working; adding them is a seal-time packaging change |
| domain-pack surface in `release/MANIFEST.sha256` | **NOT DONE** | no row pins the pack registry, so the registry bytes are the lane's root of trust; the plugin cross-checks registry-vs-verifier digests in both directions from real bytes and returns all four digests for out-of-band pinning, and says so in `non_claims` |
| W6 — the plan's named artifact list | **was OPEN when this table first said "closed"; closed by the companion commit in this wave** | see §5.1 |
| W6 other packs (units, linear algebra, statistics, ODE/PDE) | **NOT DONE** | out of scope this wave |
| W3 profiles | **closed** | verifier + 29 tests |
| W3 `>=90%` autonomous verifier-use enforcement | **NOT MEASURABLE, now machine-readably so** | `tools/eval_v2_gate.py` (added in the companion commit) reports `EVAL_V2_GATE_NOT_MEASURABLE` exit 3 with `req1 reason=no-transcript-supplied`; requirements 2 and 3 PASS. Still needs live model sessions. |
| W10 harness + frozen hidden set | **closed** | 50/50 forced run |
| W10 cross-system comparison | **NOT DONE** | needs live model sessions |
| `release/MANIFEST.sha256` | **STALE, deliberately** | generator needs build artifacts absent here |

Two `MANIFEST.sha256` rows need a seal-time repin on a machine with the built
engine and Lean binaries: `source jackal_calc.anb` and
`claim_inference_registry`. Neither was hand-edited; hand-editing a manifest row
to make a gate green is the same class of act as repinning frozen evidence.

`plugin_hermes` is a third such row, and exposing the pack lanes moved its
computed value further (it edits `tools.json` and `server.py`, both inside the
runtime-bundle identity). Pinned-vs-computed, recomputed from real bytes with
`plugin/hermes/bundle_hash.py` — the repo's own helper, not a hand-rolled
serialisation:

```
$ cd plugin/hermes && python3 -c 'import bundle_hash as b; \
    print(b.load_pinned_bundle_hash_any(b.find_repo_root()), b.compute_bundle_hash())'
pinned   e8fadc24b17884d9fc4a8458b4e4a70ac60ad0d88768b82a684c665e2a9e0202
computed 165d132aecb5376587008cfcedbdc4810f613e37f021c870535199877590ce3f
```

The row was NOT hand-edited. It is one of four surfaces of a single provenance
event awaiting the same seal-time repin.

W7/W8/W9/W11 are untouched and remain OPEN.

### 5.1 Correction: what "closed" meant when first written

The two W6 rows above originally read simply **closed**. That was an
overstatement and it is being recorded as one rather than quietly rewritten.

What was true when it was written. The behaviour was verified by hand and the
evidence in §2 is real: both routes were confirmed byte-identical to their direct
commands; the soundness refusals were observed firing from the independent
checkers; all five decision refusal paths were observed; and the anti-laundering
boundary was — and is — genuinely under test, in
`tests/domain_pack_contract_test.py::test_structural_programming_fact_cannot_be_laundered_upward`
(that file: 26 tests, `python3 -m unittest tests.domain_pack_contract_test` ->
`Ran 26 tests ... OK`).

What was not true. The governing plan's W6 section names four in-scope artifacts
under **Files** (plan lines 338, 340, 341, 342): "one manifest and frozen corpus
beside each pack", `tests/programming_pack_test.py`,
`tests/decision_pack_test.py`, and `tests/cross_pack_non_laundering_test.py`.
(Line 339, `tests/stem_pack_test.py`, belongs to the STEM pack, which this wave
never claimed. The plan itself is **not** in this repository — it lives at
`/Users/sicarii/Worktrees/jackal-codex-plugin/docs/superpowers/plans/2026-08-17-jackal-macos-juggernaut-program.md`;
the bare path cited at the top of this record is that file, not a local one.)
When this table first said "closed", the manifests existed and **the three named
test files and the per-pack frozen corpora did not exist at all**. The
anti-laundering coverage lived inside `tests/domain_pack_contract_test.py`, which
is real coverage but is not the named artifact. A reader checking the plan's file
list against disk would have found four of its items missing while the record
said the workstream was closed.

How the error happened, and why it is worth this much text. "Closed" was decided
against the substantive question — *does the pack behave correctly and refuse the
things it must refuse?* — and then reported as though it had been decided against
the plan's checklist. Nobody fabricated anything. Every command in §2 was run and
every output is real. **The claim was grounded and still outran its evidence,
because the evidence answered a different question than the claim asserted.**

That is precisely the failure `programming.source.claim_cites_test.v1` exists to
detect: a document making a claim, citing a real artifact, and the artifact not
establishing the claim. §2 records the motivating instance — an agent's
documentation asserting a test verified every polynomial moment through degree 23
when the test checked only degree 0. This record then committed the same class of
error about itself, one section later. Two independent instances in one wave is
the argument for the operation, not a counterargument.

The lead's own audit of this document against disk caught it — not a reviewer,
not CI. That is worth stating plainly, because a gate that no instrument enforces
depends entirely on someone choosing to re-read their own claims adversarially.

Resolution, as observed on disk rather than as intended. All four of the plan's
in-scope W6 artifacts now exist: `tests/programming_pack_test.py`,
`tests/decision_pack_test.py`, `tests/cross_pack_non_laundering_test.py`, and the
frozen corpora (`tests/corpus/programming_corpus_v1.json`,
`tests/corpus/decision_corpus_v1.json`, six fixture files, and their generator
`tests/corpus/generate_pack_corpus.py`). When this paragraph was first drafted
those seven paths were untracked working-tree files. They are now **tracked**:
commit `574dd55` ("test(w6): add the three named pack suites and frozen corpora
the plan requires", 12 files, 4795 insertions) added them, and
`git ls-files --error-unmatch` succeeds for all seven on this branch.

One deliberate deviation from the plan's wording, recorded rather than glossed:
the plan says "one manifest and frozen corpus **beside each pack**", which would
put the corpora under `domain_packs/programming/` and `domain_packs/decision/`.
They live under `tests/corpus/` instead, and the reason is measured rather than
assumed: `tools/domain_pack_verify.py:422` compares the on-disk inventory of
`domain_packs/` against the manifest-declared file *and directory* sets with a
plain `!=`, so any undeclared `domain_packs/*/corpus/` entry forces
`refuse("domain-pack inventory mismatch")`, and declaring it would have meant
editing a pinned manifest to admit test data.
The manifests are beside their packs as the plan requires; only the corpora moved.

A reader who finds any of those paths **absent** should treat the plan's W6 file
list as **still open**, regardless of what the table above says — the table is a
claim and the filesystem is the evidence.

---

## 6. Digest appendix — generated from disk at close, not transcribed

Every value below was read from the working tree by hashing the file, so this
section cannot drift from the artifacts the way a hand-copied digest can.

**This appendix is incomplete by construction, and says so rather than looking
complete.** It omits the W6 artifacts named in §5.1 — the three pack test files
and everything under `tests/corpus/` — because those paths were still untracked
and in flux when it was generated (they are tracked as of `574dd55`; this
appendix was **not** regenerated afterwards and still does not hash them), and a
digest table that lists a file whose
bytes may change before the commit is worse than one that admits the gap. The two
`eval_v2_gate` rows below WERE hashed here, with `shasum -a 256` on this machine
against the committed, clean working-tree copies (`git status --short` empty for
both, `git ls-files --error-unmatch` succeeds for both) — not copied from the
sibling agent's report, which independently reported the same two digests.
Whoever seals on top of this branch must regenerate the whole appendix from disk.
A digest table that quietly listed a file it had not itself hashed would be the
same defect as the one §5.1 records.

| artifact | sha256 |
|---|---|
| `jackal_calc.anb` | `f579b6f59bc024d24914487b0cd0f18ea43dea1be52708a05a66dc885d80bb4e` |
| `domain_packs/PACK_SPEC.md` | `2d76022dc2375fa3a235f05890c8b3a36ac77b008ecc5d58fb658deb253a947a` |
| `domain_packs/PACK_SCHEMA.json` | `ae15411cff7b126d1365d5fe8857bba9da5f6ef21d50dcdfab279e9634bc0073` |
| `domain_packs/registry_v1.json` | `e0f825798777f9680046e2b1b944fdbc89ddd44f8882b9047fc789c10725f7a4` |
| `domain_packs/core/manifest.json` | `427b51d6527be15286efce9ec5c90b369950f57ddb438c93e2616233e290190d` |
| `domain_packs/programming/manifest.json` | `59480b72f8ea51739859599c243b86167fb66ed3ffc519e492ca5d9f7c6605ba` |
| `domain_packs/decision/manifest.json` | `e7a8187c367a64f092c6e54bf3dd2b593265e93b8727fdffbc4bba220830e911` |
| `domain_packs/core/core_pack.anb` | `5c9e23ce102366c3e7bb2aa01c78ace6d4bc20bd2d35e0813fd62bd3c324d405` |
| `domain_packs/programming/programming_pack.anb` | `f590ed33b757fda476db5b2771e0f0a50addc838721a97b562471cc75f2153f6` |
| `domain_packs/decision/decision_pack.anb` | `8ed19f5873a2f468e01c8cb00ed0a4c39c262d84764a7559bd4e8def6a8c4b0f` |
| `tools/domain_pack_verify.py` | `22984f511208af2d7a318f1a43306d95a4b0f61876d8b44f34f39a2ded6d573d` |
| `tools/test_exists_verify.py` | `598cb99e1eb70c9410ca87345efee346f73e43aaf3625427dca17ea04231caea` |
| `tools/decision_verify.py` | `f1ad7c9fbd4c1d899dbb4bebabbbeb97e97a56bd4b279ad7d8ec3722bf12e0f6` |
| `tools/exact_verify.py` | `2c07e6257ce1524de3e31374371c6d5859dce710767156de2566ec77fa1883a7` |
| `tools/profile_verify.py` | `3af6f11df5ff2b6bc9582ff162660286224f3cf74cce8f57b68d86140f34c3c7` |
| `tools/lcm_differential_gate.py` | `dad22643e8ab913e91a3689463f5b392cb0dc9071cefb9023f45ef19ff4ff119` |
| `tools/eval_v2_gate.py` | `1a90a58f919f8bed30855c7c1d0bdfbb374e8c4bea8e417402189e1948a06f67` |
| `tests/eval_v2_gate_test.py` | `8d8d8c3e6a58b9b1e7a51b19a0923cd1672f93218083aa4ec0199469942cb09f` |
| `release/claim/inference_registry_v1.json` | `c70b33d5aee8071b5125e6a5f8ffe5226fc22a137d920c17d9b3463968be13f0` |
| `release/claim/archive/inference_registry_v1__registry_version_1.json` | `e7134ec30f3b5dce71014fa1bbfc6b15e6dd8f42bfecd900fd3a61cf6b895082` |

Self-digests and profile digests, read from inside the files:

| field | value |
|---|---|
| `registry_v1.json` `registry_digest_sha256` | `3da40d85c885626f01030152d23a010e0d354e822a53ac2e49e9f82a7f43a9d8` |
| `jackal.core.exact` `manifest_digest_sha256` | `ab851801be878e9b2ac366a992d6e1a3c709527caaffeafd8c5f3e8752f7f0b4` |
| `jackal.decision.matrix` `manifest_digest_sha256` | `9dde3c3c60920aef6bb13d131f2a9b76b57925eea7d46fd6376749c316710b04` |
| `jackal.programming.source` `manifest_digest_sha256` | `4bad241e732829bbe2c0c88790addcdb63329e9b19c7ba7c520fc910d330b890` |
| profile `core` `profile_digest_sha256` | `6957117f0401e87e38e9e616ba4ecdd100ad5a6882be3d7b8a899ae7658407ea` |
| profile `formal` `profile_digest_sha256` | `dfd876efed154ba40f223115b4cdd9c7f30cc29bcdce63bfff025f0f58f9f0b6` |
| profile `full` `profile_digest_sha256` | `f90e6838c0facbafa89329462451e167fcb4a251d75d328c7a6f12ead2aa0c7a` |
| eval corpus `aggregate_digest` | `41f4cbded9f2c6cb8f5b4ec95833e246364b6c45f6704dabe7e7c7dc189ff573` |

The archived registry hashes to `e7134ec30f3b5dce71014fa1bbfc6b15e6dd8f42bfecd900fd3a61cf6b895082`,
byte-identical to `git show 9a81b4c:release/claim/inference_registry_v1.json` — the last
registry_version 1 state of the live file, and exactly the digest the v1.6.0 fixture
records in both `pins.json` and its bundle body. That equality is what keeps the v1.6.0
replay honest; `release/evidence/**` was not touched to obtain it.

`origin/master` was merged into this branch (merge commit) because master had already
moved the live registry (adding the `formal.integral` app function, `e7c999c3` ->
`e7134ec3`) and refreshed the v1.6.0 fixture pin to match in commit 9a81b4c. Before that
merge, the branch head and the PR merge commit were two different trees, so the same
`ci_claim_admission.py` passed on `push` and failed on `pull_request`. The merged live
registry is registry_version 2 with `formal.integral` present, `c70b33d5...`.

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

---

## 7. Post-PR #11 unified reconciliation — 2026-08-20

This section supersedes only the open seal-time rows in §5; the earlier branch
history remains evidence of what was true before reconciliation.

Observed current surface:

```text
python3 tools/profile_verify.py
core=3 formal=13 full=41
profile_verification=verified tools_declared=41 nesting=core<=formal<=full OK
```

The four domain-pack tools remain present. Three Anubis program-evidence tools
were added to `full` only. `core` and `formal` membership and digests did not
move.

Mechanically closed package rows:

- `domain_packs/`, all three pack sources/manifests, `PACK_SCHEMA`,
  `PACK_SPEC`, the pack verifier, and all three operation checkers are shipped;
- the program verifier, `inventory-safe-v1` policy, specification, wrapper,
  profiles, and profile schema are shipped;
- `release/MANIFEST.sha256` is generated by
  `release/tools/repin_v173.py`; it now pins the domain registry/verifier/
  checkers and program verifier/policy;
- the package plugin lists all 41 tools from a fresh extraction;
- missing pack bytes refuse pack calls without breaking `jackal_exact`;
- a missing program verifier refuses plugin startup rather than leaving a
  declared unreachable tool.

`release/build_package_v173.sh --build` produced two byte-identical tarballs:

```text
tarball sha256       c030076186791a551d7818412e39ea895da0f16a2fad88877554ff390c284d9c
tarball bytes        158362703
files                106
SHA256SUMS sha256    15b179469a3519d124706a1b3281710ca2870e28a7073d107ac15eec156f2894
```

The canonical package parity instrument was re-pointed from the superseded
v1.7.0 builder. Its mutation control restores that old target and observes
`superseded-builder`; the live gate reported
`CLAIM_PACKAGE_PARITY_PASS rows=60 failures=0`.

Program policy decision: `contracted-safe-v1` is refused. The admitted
`inventory-safe-v1` profile checks producer-attested function/policy
inventories but explicitly leaves construct-total walker coverage open.
COVENANT replay used nine proof objects and 615 RUP additions; repository and
package CLI/plugin paths reproduced receipt
`8341ec180add6475f193f47e218b7af88fe2ef6437474c92ede4dfe1ecc02423`.
A self-consistent assurance edit refused `receipt-semantic-mismatch`, and the
following pristine replay verified again.

W10 remains `NOT_MEASURABLE`, not PASS. Three fresh Codex JSONL transcripts
record attempted W3/W10 MCP calls. The noninteractive host cancelled every MCP
call; the deterministic runner still emits no model/profile identity and has no
Codex-event adapter. `tools/eval_v2_gate.py` returned exit 3.

W6 units, linear algebra, statistics, and ODE/PDE packs remain out of scope.
The current governing record already classified them as not done rather than
mandatory for this release (§5 row 524); no new pack was added here.

PR #10 remains an open draft and was not merged, closed, rewritten, or absorbed.
If its chronology accept-condition change lands first, the claim verifier,
plugin bundle, manifest, package, and all package hashes above must be
regenerated; this candidate cannot silently absorb it.

Terminal state remains `SIGNOFF_REQUIRED`: architect review is required for the
new program-verifier accept conditions and the domain-pack minimum-release
change from v1.8.0 to v1.7.3 before merge/tag/publication.
