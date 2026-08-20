# Model-only arm — 2026-08-19

W10 requires a recorded `model-only vs JACKAL` comparison. This is the model-only
arm. It was previously reported as blocked on "a live model session"; that was
wrong, and this file exists because the blocker was self-imposed.

**Headline: the model-only arm scored 33/33 on every item this corpus can score
it on. This corpus does not discriminate model from tool.** That is a finding
about the instrument, not a finding about either the model or the engine.

## Method

One stateless completion per item, no tools, no calculator, no conversation
history, no retries. System prompt: *"You are answering a mathematics question
with no tools and no calculator. Give the exact answer. Do not show working.
Answer in one short line."* Prompt: the item's `question` field verbatim.

Scored on the **mathematical value**, not on stdout bytes. A model that is not
running the engine cannot be expected to emit `status=exact r=24`, so scoring by
`stdout_contains` would measure format compliance and call it arithmetic.

## What was excluded, and why

Of 50 corpus items, 34 are scoreable for a model-only arm.

| Excluded | n | Reason |
|---|---|---|
| `refusal_expected` | 8 | `corpus.py:19` excludes them from `accuracy` by design; refusing well is scored by the refusal metrics, not this one |
| `programming_status` | 6 | They assert facts about bytes on disk — file content hashes, declaration line numbers, the engine's own maturity table. A model with no file access cannot answer them. Scoring them would measure tool access and report it as arithmetic ability |
| `ra.canon.half_plus_third.v1` | 1 | Requires reproducing JACKAL's internal canonical S-expression form *and* a SHA-256 digest of it. Tool-format, not mathematics |
| `en.range_bound_cert.x2_unit.v1` | 1 | Requires emitting a JACKAL certificate envelope. Tool-format, not mathematics |

Marking those 16 wrong would have produced a defensible-looking 33/49 = 67% and
that number would have been a lie about a model, caused entirely by scoring
tool-access as arithmetic.

## Instrument validation — done before the number was read

The scorer was run against two controls first:

- **positive control** — feed each item its own true answer: must score 34/34
- **negative control** — feed each item an answer definitively *wrong for that
  item*: must score 0/34

It failed both on the first attempt (33/34 and 2/34) and the repair introduced a
third defect. Three scorer defects total:

1. A single global junk string was used as the negative control. It contained the
   words `false` and `composite`, which are the *correct* answers to two items, so
   those items "passed" on junk. A negative control has to be wrong **per item**.
2. A degenerate interval `[1/3, 1/3]` can never contain a decimal approximation
   of `1/3`. Point intervals now get a relative pad, and the number-extractor
   parses fractions (`1/3`) and not only decimals.
3. The symbolic-`e` endpoint check was written as `"e" in answer`, which matches
   the letter *e* inside ordinary English words — `"the value is 11.0"` passed.
   Now `(?<![a-z])e(?![a-z])`.

Defect 3 was introduced by the fix for defects 1–2 and was caught only because
the controls were re-run after the repair.

**Both of the initially-reported "misses" were scorer false negatives, not model
errors.** The model answered *"No — 4 = 2 × 2, so 2 is a divisor"* (correct, in
natural language, where the scorer demanded the literal token `composite`) and
*"[1/3, 1/3]"* (exactly right, where the scorer could not parse a fraction). The
first reading was 31/33 = 93.9%.

That error had a direction. **A scorer defect that makes the untooled arm look
worse flatters the tool this repository exists to promote.** Reporting 93.9%
without inspecting the misses would have published a number biased in favour of
the thesis. The correct reading is 100%.

## Result

```
graded                                 33 / 34   (1 item errored on the API call: ei.mod_pow.fermat_p64.v1)
correct                                33 / 33 = 100.0%
items whose true answer exceeds i64     8 / 8
lcm-overflow items                      3 / 3
```

The `lcm` overflow items deserve their own line. `ei.lcm.overflow_2_62_x3.v1`,
`ei.lcm.overflow_3_x2_62.v1` and `ei.lcm.overflow_i64max_x2.v1` are the three
cases where **the engine itself returned a wrong answer** until the fix landed in
this branch — `lcm(2^62, 3)` printed `4611686018427387904`, a value *smaller than
one of its inputs*, while `maturity` declared the command `class=exact`.

The untooled model got all three right, immediately, because a model reasoning
symbolically has no 64-bit register to overflow. On precisely the items that
motivated this branch's headline defect fix, the tool was wrong and the model was
right.

## What this means, stated plainly

**The corpus cannot answer the question W10 asks it.** It was seeded by running
the pinned engine and recording its bytes (`corpus.py:4-8`), which makes it a good
instrument for detecting engine regressions and a poor one for measuring whether a
tool improves on a model. Its `exact_integer` items are standard number theory on
small inputs, plus a handful of big-integer products — all of which a current
model does unaided.

A corpus that discriminates would need items where an untooled model actually
fails. Candidates, none of which are in the corpus today:

- long chains where per-step rounding compounds (the `settlement_code` shape:
  round-every-period vs round-once diverge, and the divergence is the answer)
- exact rational arithmetic over enough steps that decimal drift is detectable
- canonicalisation and content digests — genuinely tool-only, which is exactly
  why the two items of this kind were excluded above rather than counted
- certified enclosures, where the deliverable is a *proof-carrying* interval and
  not a number, so a confident correct guess still fails the actual requirement
- adversarial near-ties and boundary cases where a plausible wrong answer is
  more available than the right one

## Non-claims

- This is **one** arm of the comparison, on **one** model, in **one** run, with
  n=33. It is not an effect size and no significance is claimed.
- It says nothing about the model family named in the original effect-size
  question. It measures whatever model `completion()` routes to.
- 100% here is **not** evidence that tools are unnecessary. It is evidence that
  *this corpus* does not test the thing tools provide. The engine's value on
  these items was never the arithmetic — it was the certificate, the refusal
  channel, and the declared epistemic class, none of which a free-text answer
  carries and none of which this arm scored.
- Temperature, sampling parameters, and model identity behind `completion()` were
  not pinned. A rerun may differ. `[NEEDS-HUMAN]` to pin them if this is ever
  cited as a baseline.
- The raw per-item answers are in `model_only_arm_2026-08-19.json` beside this
  file. Read them rather than trusting this summary.
