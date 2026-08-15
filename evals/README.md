# evals/ — JACKAL v1.4.x empirical evaluation harness (eval_v1)

## Dry-run output

```
$ python3 evals/runner.py --dry-run
corpus size: 2000 problems
runners accepted: model_only, model_dc, model_python, model_jackal, model_jackal_verified
conditions: ['model_only', 'model_dc', 'model_python', 'model_jackal', 'model_jackal_verified']
categories: ['arith', 'frac', 'int', 'diff', 'sing', 'thr', 'dec', 'ref', 'unit', 'root']
```

Corpus is deterministic (seed = 20260815); every run produces byte-identical
problems.

## What this measures

For a single model family (Anthropic Claude — the only model surface
available to this environment), how much do calculator / language-runtime /
JACKAL / verified-JACKAL tool paths reduce **confidently-wrong** numerical
claims versus **model-only** prose?

Five tool conditions, ten problem categories, seeded corpus of 200 problems
per category, 10 000 total observations. The report at `evals/report.md`
gives per-condition × per-category numbers and a top-line roll-up. Every
row is derived from a real call — real Claude, real `dc`, real
`python3`, real `./jackal-native`, and (where the plugin bundle accepts)
real `plugin/hermes/jackal_hermes call jackal_verify_receipt`.

## Scope (honest)

- **Model family**: Claude only. This is a WITHIN-MODEL, five-tool-condition
  comparison. It is not cross-model — no GPT/Gemini/etc.
- **Model tag**: `smol` = `claude-haiku-4-5` via the OMP eval-kernel
  `completion()` function. The offline reproduction path uses
  `evals/completion_bridge.py` (Anthropic Messages API, key required).
- **Scale run**: 200 problems / category × 10 categories × 5 conditions
  = 10 000 observations. Elapsed ~19 min (~9 obs/s wall).
- **Machine**: Apple M4 Max, darwin 25.6.0, single process pool, single
  session.
- **Pinned identities**: the runner emits every result row alongside the
  contents of `release/MANIFEST.sha256` so a reader can pin exactly which
  evaluator/checker/plugin bytes were exercised. Both the main JSONL and
  the report include the manifest.
- **Not measured**: cost, energy, security posture, prompt-injection
  robustness, sample-efficient learning, jailbreak resilience. Out of
  scope.

## Files

| file | purpose |
|---|---|
| `corpus.py` | seeded generators for 10 categories (200/cat by default) |
| `metrics.py` | Observation / Judgment / Aggregate dataclasses + `judge()` |
| `conditions.py` | five runners: `model_only`, `model_dc`, `model_python`, `model_jackal`, `model_jackal_verified` |
| `runner.py` | dispatch + report writer (`--dry-run`, `--scale N`, `--model {auto,live,stub,bridge}`) |
| `completion_bridge.py` | subprocess-callable CLI wrapping Anthropic Messages API |
| `report.md` | latest generated report (per-condition × per-category tables + supplementary) |

## Evidence

Written to `release/evidence/eval_v1/`:

| file | rows / bytes | note |
|---|---|---|
| `results.jsonl` | 10 000 rows | main run; each row: {problem, observation, judgment, pins, run_scale, model_kind} |
| `supplementary_A_verifier_active.jsonl` | 400 rows | forced `<JACKAL_RANGE>` stub; every verifier call is real |
| `supplementary_B_direct_checker.json` | 1 | pinned Lean checker ACCEPTs a fresh range-bound cert for `x^2 [0,1]` |
| `supplementary_C_plugin_refusal.json` | 1 | verbatim `plugin/hermes/jackal_hermes selftest` output during Supp A: `plugin-bundle-mismatch` |

## Reproducing

Dry-run (no API / no tool calls needed):

```
python3 evals/runner.py --dry-run
```

Full scale, offline model (deterministic tool-request stub, all tool calls
real):

```
python3 evals/runner.py --scale 200 --model stub --verbose
```

Full scale via subprocess bridge (requires `ANTHROPIC_API_KEY`):

```
export ANTHROPIC_API_KEY=sk-ant-...
python3 evals/runner.py --scale 200 --model bridge --workers 32 --verbose
```

Restricted slices:

```
python3 evals/runner.py --scale 50 --conditions model_python,model_jackal \
    --categories arith,unit --model stub
```

## Judge rules

- **CORRECT**: extracted answer matches ground truth within tolerance
  (exact for rationals; ulp for f64; `rel:1e-9` for estimated) OR
  `expected_status = refused` and observed status is `refused`.
- **CONFIDENTLY WRONG**: extracted answer ≠ ground truth (beyond tolerance)
  AND the reply contains no hedge word (`approximately`, `about`,
  `estimate`, `roughly`, `~`, `≈`).
- **FALSE EXACT LABEL**: reply labels itself `exact` / `certified` /
  `bounded` but disagrees with ground truth.
- **ESTIMATE INFLATION**: `claimed_status ∈ {exact, bounded, formal-bounded}`
  but extracted answer ≠ ground truth.
- **VERIFICATION CATCH**: `jackal_verify_receipt` was invoked AND its
  verdict aligns with the judge's correctness call.

## Zero-fabrication contract

Every number in `report.md` and `results.jsonl` is the direct product of a
real subprocess or API call executed in this repo, on this machine, during
this session. Failure modes (a plugin bundle mismatch, a `shlex.split`
quoting error, a model refusal) are recorded as observations and appear in
the table verbatim. Nothing is smoothed, imputed, or synthesized.
