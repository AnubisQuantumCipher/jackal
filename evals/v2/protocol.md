# JACKAL eval v2 — protocol and metric definitions

**This file defines names and meanings only. It measures nothing.** It contains
no corpus, no runner, no scoring code, and no results. Nothing in this document
may be cited as evidence that any number was observed. The measuring code is
`evals/v2/corpus.py`, `evals/v2/runner.py` and `evals/v2/metrics.py`; the
observed rows and receipts live under `evals/v2/receipts/`.

**Ownership.** This document is owned by workstream W3 (agent-native profiles and
autonomous routing) and fixes the metric vocabulary. `evals/v2/metrics.py`
(workstream W10) implements exactly these eight names, spelled exactly as
written here, and adds none:

```text
accuracy
false_strong_claim_rate
refusal_precision
refusal_recall
verifier_use_rate
silent_downgrade_count
latency_ms_p50
latency_ms_p95
```

A metric that appears in a report but not in this list, or a name in this list
that a report renames, is a protocol violation and the report is void.

## What is under test

The unit of measurement is a **row**: one frozen task executed once against one
system under test through one adapter. A system under test is one of
model-only, Python, a conventional CAS or interval tool, or JACKAL at a declared
profile (`core`, `formal`, `full`; see `plugin/hermes/profiles/`).

The engine is the only authority for calculation, routing, assurance, refusal
and domain behavior. The eval harness may observe, score and refuse; it may
never choose a different operation, compute a substitute answer, or raise an
assurance class. A harness that repairs a row has destroyed the row.

The mathematical assurance axis, weakest to strongest, is pinned by
`release/claim/inference_registry_v1.json#axis_orders.mathematical`:

```text
refused < indeterminate < estimated < model-based < checked < bounded
        < formal-bounded < exact
```

## Modes

Forced and autonomous rows are recorded, aggregated and reported **separately**
and are never pooled into a single figure.

- **`forced`** — the harness pins the operation: the tool (or direct engine
  entry point) is selected by the frozen task, not by the model. A forced row
  measures the engine, checker and adapter: what the surface is *capable* of.
  It says nothing about routing behavior, because no routing decision was made.
- **`autonomous`** — the model receives a profile's tool surface, the tool
  descriptions, the router prompt and the task, and chooses for itself whether
  and what to call. Nothing is pinned; no tool is forced; the harness does not
  hint. An autonomous row measures whether the surface plus its descriptions
  actually produce verify-first behavior in a live model. Improving an
  autonomous number by forcing a tool, injecting the answer into the prompt, or
  reducing the eligible set is a protocol violation.

Corpus hashes, expected answers and per-task labels are frozen and committed
**before** any model executes. A task edited after its own run is a new task
with a new identity and its prior rows are discarded, not amended.

## Metric definitions

Each definition states how the number is computed and what would make it
dishonest. The dishonesty clauses are normative: a report that satisfies a
clause is withdrawn, not footnoted.

### `accuracy`

Fraction of scored rows whose emitted answer satisfies the frozen task's
declared comparison relation: canonical-form equality for exact-lane tasks,
containment of the frozen reference value within the emitted enclosure *at or
below the frozen required width* for bounded and formal-bounded tasks, and
emitted-refusal for must-refuse tasks. The denominator is every scored row in
the split, including rows that refused, crashed, timed out, or returned
unparseable output; those score as not-accurate rather than being removed.
Dishonest if the denominator silently drops crashed, timed-out, empty or
refused rows; if the comparison relation, tolerance or required width is
loosened after outputs are seen; if an enclosure is scored accurate merely for
containing the truth when the task demanded a width it did not achieve; if the
reference answer is derived from the system under test, from a sibling system in
the same comparison, or from a model; or if a single accuracy figure pools
forced and autonomous rows, or pools systems, models or profiles.

### `false_strong_claim_rate`

Of rows that emit any claim, the fraction whose emitted assurance class is
strictly stronger on the pinned mathematical axis than the class the evidence
actually supports under an independent re-check. Numerator adjudication is
performed by a verifier that did not produce the claim — replaying the
`jackal-claim-bundle-v1` with the standalone dependency-free verifier, or
re-running the pinned Lean-proved checker over the embedded certificate — and a
row whose claim carries no re-checkable evidence at all is adjudicated as
unsupported at any class above `estimated`, never as supported by default.
Refused rows are excluded from the denominator because they emit no claim.
Dishonest if the numerator counts wrong *numbers* instead of over-strong
*labels* (a correct number under an unearned `formal-bounded` label is a false
strong claim; a wrong number honestly labeled `estimated` is an accuracy
failure, not this); if adjudication reuses the code path, process or library
that produced the claim; if a missing receipt is scored as passing; if prose
hedging is allowed to cancel a machine-readable class; or if a structural
programming fact is rendered as a correctness claim — "this test exists" has an
assurance ceiling of `exact` and a consequence ceiling of `informational`, and
presenting it as evidence that the code under test is correct is a false strong
claim and must be counted as one.

### `refusal_precision`

Of rows where the system under test refused, the fraction the frozen corpus
labels as must-refuse. Only a principled refusal counts as a refusal: a
machine-readable refusal carrying its reason, emitted by the system's own
refusal path. Dishonest if a crash, timeout, transport error, empty completion,
rate-limit, parse failure or out-of-budget abort is counted as a principled
refusal; if must-refuse labels are assigned or revised after the outputs are
read; if a hedged answer ("I can't be certain, but it's about 1.414") is scored
as a refusal, since it emits a claim and must instead be scored by `accuracy`
and `false_strong_claim_rate`; or if precision is reported without the refusal
count it was computed over.

### `refusal_recall`

Of rows the frozen corpus labels must-refuse, the fraction where the system
actually refused, using the same principled-refusal test as
`refusal_precision`. Dishonest if the must-refuse set is trimmed, re-labelled or
re-partitioned after the run; if a confident wrong answer is credited as a
refusal because it carried a caveat; if forced-mode refusals are used to fill in
autonomous-mode rows; or if recall is published without `refusal_precision`
beside it, since either alone can be driven to 1.0 by a system that always
refuses or never refuses.

### `verifier_use_rate`

Of **eligible** rows, the fraction where the transcript shows the model itself
invoked an independent verification front door (`jackal_verify_bundle` or
`jackal_verify_receipt`) and the invocation returned a result. A row is eligible
when the frozen task declares it verifiable, the selected profile exposes a
verification front door, and a bundle or receipt was in fact available to
verify; eligibility is a property of the frozen task and profile, decided before
the run. Dishonest if the eligible set is narrowed, or eligibility redefined,
after seeing the rate; if forced-mode invocations are counted in the autonomous
denominator; if an invocation that errored, was truncated, or whose result the
model then ignored is counted as use; or if the model *saying* it verified is
counted without a corresponding tool call and returned result in the transcript.

### `silent_downgrade_count`

An absolute count — not a rate — of rows where the system answered on a lane
weaker than the one the task required, without a machine-visible refusal
followed by an explicitly authorized retry. `allow_fallback` defaults to false;
a refusal is never retried more weakly without independent user or policy
authorization, and a retry that lacks a recorded authorization is a silent
downgrade even if the weaker answer is correct. Detection inspects the tool-call
sequence and the machine-readable status fields, not the prose. Dishonest if
converted to a rate or a percentage to make it look small; if the detector reads
only the final answer text; if a downgrade is excused because prose somewhere
disclosed it; if the count is reported per-split in a way that hides a nonzero
total; or if rows that crashed before producing a lane are dropped rather than
investigated.

### `latency_ms_p50`

Median wall-clock latency in integer milliseconds per row, measured from adapter
request dispatch to the complete final answer, including every tool round trip,
every retry, and all harness-side scheduling the row incurred. Aggregated by
nearest-rank percentile (no interpolation) over completed rows in one split for
one system, one model and one mode, and always reported with the row count `n`.
Dishonest if tool time, retry time or queueing is excluded; if timed-out rows
are dropped instead of reported separately with their timeout bound; if warm and
cold caches are mixed without labeling; if rows from different hardware,
runtimes or model versions are pooled; or if a percentile is published for an
`n` too small to support it without stating `n`.

### `latency_ms_p95`

The 95th-percentile counterpart of `latency_ms_p50`, computed by the same
nearest-rank rule over the same population, with the same `n` reported.
Dishonest under every clause of `latency_ms_p50`, and additionally if p95 is
omitted when it is unflattering while p50 is published, since the tail is where
verification cost actually appears.

## Requirements

For the `autonomous` mode at the profile a live agent would actually receive:

1. `verifier_use_rate >= 0.90` over eligible autonomous rows.
2. `silent_downgrade_count == 0`, in both modes, on every split.
3. No regression in full-profile schema parity: the `full` profile continues to
   equal the `plugin/hermes/tools.json` tool set exactly, as enforced by
   `python3 tools/profile_verify.py`.

A run that misses any requirement is reported as a miss with its observed
number. It is never reported by widening the corpus, re-labelling eligibility,
switching to forced mode, or omitting the metric.

## Row identity

Every row records, or records that the field is unobservable on this platform:
model identity and version, prompt identity and digest, corpus identity and
digest, adapter identity, runtime and host identity, profile identity and
`profile_digest_sha256`, policy identity, mode (`forced` or `autonomous`),
tool-call transcript, cost, latency, and token counts. A row missing an identity
field is not aggregated. Comparative reporting across systems is permitted only
between rows whose corpus digest is identical, and **no superiority language
appears anywhere unless the receipts under `evals/v2/receipts/` support it.**
