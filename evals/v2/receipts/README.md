# `evals/v2/receipts/` — what a results receipt binds, and what it does not

A receipt in this directory is a JSON file written by `evals/v2/runner.py`
(schema `jackal-eval-v2-results-v1`). It exists so a number in a report can be
traced back to the exact question set, the exact build, and the exact bytes that
produced it.

Read this file before quoting any metric out of a receipt.

## What a receipt binds

A receipt binds five things, each recomputable from the receipt plus the repo.
The first four are single top-level fields and are all REQUIRED: a file missing
any of them is not a receipt, because it does not say which corpus, which build,
which mode or which moment it is a measurement of. `metrics.py
--verify-receipts` refuses such a file by naming the absent field and exits
non-zero rather than printing a metric. That includes the degenerate case of a
bare JSON list of records, which is refused for all four reasons at once.

```
corpus_aggregate_digest   engine_identity   mode   timestamp_utc
```

1. **The corpus it was scored against.** `corpus_aggregate_digest` is the
   canonical SHA-256 over the ordered list of per-item digests, where each item
   digest is SHA-256 over `{item_id, question, expected}` serialised with
   `sort_keys=True, separators=(",",":"), ensure_ascii=False`. Every record also
   carries its own `item_digest`. If a question or an expected answer is edited,
   every digest moves and `metrics.py --verify-receipts` exits non-zero. A
   receipt therefore cannot be silently re-pointed at an easier corpus.

2. **The engine identity.** `engine_identity` records the compiler path and its
   SHA-256, the SHA-256 of `jackal_calc.anb`, and the SHA-256 of the compiled
   artifact that was actually executed. Two receipts with different
   `artifact_sha256` are measurements of two different programs and must not be
   compared as if one were a regression of the other.

3. **The mode.** `mode` — `forced` means the harness itself invoked the engine on
   every item. `autonomous` means `invoked_tool` was populated only from a
   human-supplied `--transcript`. `model_invoked` is always `false`: the runner
   has no model client. See the caveat string carried in every receipt.

4. **The moment.** `timestamp_utc` is when the run happened. A receipt is a
   measurement of one build at one time, and a receipt that cannot say when it
   was taken cannot be placed relative to any other receipt.

5. **The observed bytes.** Each record carries `exit_code`, `raw_stdout` (capped
   at 4096 characters), `raw_stdout_len`, `raw_stdout_sha256` over the **full**
   untruncated stdout, `raw_stderr`, `parsed_status`, `refusal_reason`, the
   measured `latency_ms`, and — when the item failed — `failure_notes` naming
   which check failed. Nothing is scored from a summary; everything is scored
   from these bytes. That is why the consequence class a record asserts is read
   out of `raw_stdout` (the engine's own `consequence=` line) rather than from any
   field a producer could omit.

## What a receipt does NOT establish

- **It is not evidence that the engine is correct.** A receipt is evidence of
  what *this* corpus observed on *this* build at *this* timestamp. The corpus is
  50 items. The engine's own `maturity` output says the same thing about itself:
  `non-claim=universal-correctness; finite campaigns cannot establish it`. A
  receipt in which every item passes means every item in this finite question set
  passed, and nothing wider.

- **It is not evidence about untested lanes.** The corpus touches the exact
  integer, rational, enclosure and refusal lanes plus six structural facts. It
  does not touch the `approximate`, `estimated`, `checked` or `model-based`
  classes at all. Silence about a lane in a receipt is silence, not a pass.

- **A `programming_status` pass is never a correctness claim.** Those items check
  bytes: four check the engine's own `maturity` text, and two run the programming
  operations `test-exists` and `claim-cites-test`. Their assurance ceiling is
  `exact` — the bytes are or are not there — but their consequence ceiling is
  `informational`, and those are two SEPARATE registry axes.
  `ps.maturity.lcm_declared_exact.v1` passing means the maturity table lists
  `lcm` under `class=exact`, which is a fact about a string and not about the
  command. The two operation items go further and assert nothing at all about any
  file in this repository: their argv carries a synthetic path and a declared
  all-zero content hash, because the engine validates only the canonical FORM of
  a caller-supplied structural fact and never opens the file. Binding such a
  claim to real bytes is `tools/test_exists_verify.py`'s job, and it refuses both
  of those certificates. What those two items establish is that the form gate
  holds and that the engine stamps both axes itself. Every `programming_status`
  item carries a `note` field stating its own scope limit; quote the note
  whenever you quote the item.

- **It does not establish that a certificate was checked.** The corpus runs the
  certificate *emitters* (`prime-cert`, `range-bound-cert`, the
  `jackal-exact-cert-v1` lines). It does not run the Lean-proved checker over
  them. `eligible_for_verifier` marks items where a verifier lane exists, not
  items where a verifier was run.

- **`verifier_use_rate` is not a model measurement.** In `forced` mode the
  harness sets `invoked_tool` itself, so the rate is 1.0 over eligible items by
  construction and tells you about the harness. In `autonomous` mode with no
  `--transcript`, it is 0.0 because no transcript was supplied — not because a
  model declined to verify. Only an `autonomous` receipt with a real
  `transcript_path` from a live session says anything about model behaviour.

- **A `None` metric is not a good score.** `refusal_precision`,
  `refusal_recall`, `accuracy` and `verifier_use_rate` return `None` on an empty
  denominator rather than `1.0`. `None` means undefined, and a report that
  renders it as perfect is wrong.

- **Latencies are wall-clock on one machine.** `latency_ms_p50` and
  `latency_ms_p95` are nearest-rank percentiles over uninstrumented
  `subprocess.run` wall time on whatever host produced the receipt, with no
  warm-up control beyond building the engine once before the first item. They are
  usable for order-of-magnitude comparison on the same host and not for anything
  finer.

## Live Codex transcripts — 2026-08-20

The three `codex_w*_2026-08-20.jsonl` files are captured `codex exec
--ephemeral --json` event streams, not `jackal-eval-v2-results-v1` receipts.
The autonomous W3 stream has one command-execution event whose private local
command and output payloads are explicitly redacted while its event type,
identity, status, and exit code remain. Their exact post-redaction hashes,
content state, and adjudication are in `live_tool_sessions_2026-08-20.json`.

Observed:

- autonomous W3 attempted `jackal_range_bound` instead of the receipt verifier;
- forced W3 attempted the correct `jackal_verify_receipt`;
- autonomous W10 attempted `jackal_decision_rank_v2` and disclosed that its
  fallback arithmetic answer was not verifier-established;
- the noninteractive host cancelled every MCP call, including with
  `approval_policy=never`.

Therefore attempted invocation is recorded, but successful verifier use remains
`NOT_MEASURABLE`. The deterministic runner also still lacks profile identity and
an adapter from Codex JSONL events to protocol-admissible autonomous rows. These
transcripts must not be passed to `metrics.py --verify-receipts` or counted as a
model/tool accuracy comparison.

## Reproducing a receipt

```
python3 evals/v2/corpus.py --self-check
python3 evals/v2/runner.py --mode forced --out evals/v2/receipts/<name>.json
python3 evals/v2/metrics.py --verify-receipts evals/v2/receipts/<name>.json
```

`--verify-receipts` recomputes all eight metrics from the records rather than
reading any stored metric, and exits non-zero if:

- any of the four required top-level fields is absent or null — a receipt that
  does not bind its corpus, build, mode and moment is not scored at all;
- a record is missing a required record field;
- the recorded corpus digest does not match the live corpus;
- a record names an item that is not in the corpus;
- a record asserts a status token that is not on the registry mathematical axis,
  or a `consequence=` class that is not a registry consequence class. An
  unrecognised token is refused rather than given a default rank: scoring a claim
  whose assurance nobody has placed on an axis is exactly the laundering step
  this harness exists to prevent.
