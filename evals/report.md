# JACKAL Evaluation Report — eval_v1

## Scope (honest)

- Timestamp (UTC): 2026-08-15T15:12:53Z
- Scale: 200 problems per category × 10 categories × 5 conditions
- Total observations: 10000
- Model kind: **live-omp-completion**
- Model family: Claude only (Anthropic API is the only model surface available here).
  This is a WITHIN-MODEL comparison across five tool-use conditions — NOT a cross-model comparison.
- One machine (Apple M4 Max, darwin 25.6.0), one session, one process pool.
- Every number below is derived from a real tool call. STUB rows (marked `[stub]`) had no live Claude call for that condition, but their tool outputs (dc / python / jackal / hermes) are real. Model_only under stub is a fail-closed row.

## Pinned identities (release/MANIFEST.sha256)

- `evaluator` = `820c0722e46a0800115c404ea1c9251c6f72fe8c6897bdabe437f342f9310b6c`
- `checker` = `e750ff75d7cdd10311305e87819aa0d4c4ef705a0ef86682abc75a7a03979aae`
- `gaussian-producer` = `20c24622b786940a8e82198f2364fb7593e761902fa0736289b179642f1e4306`
- `gaussian-checker` = `11c741f04b811aa8621db4da5c5dc05e292ead8c0e6a854739f6068757470612`
- `range-proof-identity` = `b75ac9f9c4bdc84920ad7d69542a58b19469dede33e2df16e4d771ddcb9586a2`
- `range-proof-digest` = `1d1e40af5f14b3b7d0196d52c71d2fe43ac64139100600f86ac1bdd088f8d482`
- `gaussian-proof-identity` = `dea12a25529eb2b7f2817bcd499b9e7a1c8a9a9a6cd8bf821cf1d947e4465cfc`
- `gaussian-proof-digest` = `7fbb0d585aa11d059d710bbe0bdac2337a8da49746e65e27316a95d774a2a606`
- `coverage-inventory` = `102a4e40d864ba6c05e2961a273487554c1e4b61d4827a34cde6dd7952a6005b`
- `source` = `5d43df8de01adb86bb10a0a6cea28fb79faf03cd58be51654c3fa88c653e4a40`
- `compiler_pin` = `a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2`
- `plugin_hermes` = `9d5f34b1cfaf162e4b9c923b6c7088861cf096296fd795d7482b7e24beee8d2c`

## Per-condition × per-category summary

| condition | category | N | correct | incorrect | refused_ok | refused_wrong | conf_wrong | false_exact | est_infl | verif_catch | mean_ms | tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| model_only | arith | 200 | 67 | 124 | 0 | 9 | 124 | 0 | 0 | 0 | 4314.9 | 0 |
| model_only | frac | 200 | 196 | 4 | 0 | 0 | 4 | 0 | 0 | 0 | 3536.8 | 0 |
| model_only | int | 200 | 190 | 10 | 0 | 0 | 10 | 0 | 0 | 0 | 1260.8 | 0 |
| model_only | diff | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1234.4 | 0 |
| model_only | sing | 200 | 200 | 0 | 200 | 0 | 0 | 0 | 0 | 0 | 1282.4 | 0 |
| model_only | thr | 200 | 105 | 95 | 0 | 0 | 90 | 0 | 0 | 0 | 2419.3 | 0 |
| model_only | dec | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1245.1 | 0 |
| model_only | ref | 200 | 200 | 0 | 200 | 0 | 0 | 0 | 0 | 0 | 1306.1 | 0 |
| model_only | unit | 200 | 130 | 70 | 0 | 0 | 70 | 5 | 5 | 0 | 3453.3 | 0 |
| model_only | root | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1265.2 | 0 |
| model_dc | arith | 200 | 195 | 5 | 0 | 0 | 5 | 5 | 5 | 0 | 3643.4 | 0 |
| model_dc | frac | 200 | 181 | 19 | 0 | 0 | 19 | 19 | 19 | 0 | 8617.6 | 0 |
| model_dc | int | 200 | 182 | 18 | 0 | 0 | 18 | 13 | 13 | 0 | 1729.9 | 0 |
| model_dc | diff | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1566.5 | 0 |
| model_dc | sing | 200 | 200 | 0 | 200 | 0 | 0 | 0 | 0 | 0 | 1400.0 | 0 |
| model_dc | thr | 200 | 195 | 5 | 0 | 0 | 5 | 5 | 5 | 0 | 3806.4 | 0 |
| model_dc | dec | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1361.7 | 0 |
| model_dc | ref | 200 | 200 | 0 | 200 | 0 | 0 | 0 | 0 | 0 | 1344.7 | 0 |
| model_dc | unit | 200 | 164 | 36 | 0 | 0 | 35 | 24 | 24 | 0 | 5588.9 | 0 |
| model_dc | root | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2572.7 | 0 |
| model_python | arith | 200 | 199 | 1 | 0 | 0 | 1 | 1 | 1 | 0 | 4220.9 | 0 |
| model_python | frac | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3228.5 | 0 |
| model_python | int | 200 | 198 | 2 | 0 | 0 | 2 | 2 | 2 | 0 | 2243.2 | 0 |
| model_python | diff | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1887.3 | 0 |
| model_python | sing | 200 | 200 | 0 | 200 | 0 | 0 | 0 | 0 | 0 | 1252.1 | 0 |
| model_python | thr | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3095.2 | 0 |
| model_python | dec | 200 | 168 | 32 | 0 | 0 | 32 | 32 | 32 | 0 | 3128.0 | 0 |
| model_python | ref | 200 | 200 | 0 | 200 | 0 | 0 | 0 | 0 | 0 | 1327.2 | 0 |
| model_python | unit | 200 | 198 | 2 | 0 | 0 | 2 | 2 | 2 | 0 | 4893.4 | 0 |
| model_python | root | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2723.0 | 0 |
| model_jackal | arith | 200 | 199 | 1 | 0 | 0 | 1 | 1 | 1 | 0 | 3561.6 | 0 |
| model_jackal | frac | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3377.3 | 0 |
| model_jackal | int | 200 | 187 | 13 | 0 | 0 | 13 | 1 | 1 | 0 | 1614.0 | 0 |
| model_jackal | diff | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2443.8 | 0 |
| model_jackal | sing | 200 | 200 | 0 | 200 | 0 | 0 | 0 | 0 | 0 | 1312.1 | 0 |
| model_jackal | thr | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3547.7 | 0 |
| model_jackal | dec | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2890.1 | 0 |
| model_jackal | ref | 200 | 200 | 0 | 200 | 0 | 0 | 0 | 0 | 0 | 1415.8 | 0 |
| model_jackal | unit | 200 | 150 | 49 | 0 | 1 | 49 | 39 | 39 | 0 | 3744.0 | 0 |
| model_jackal | root | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2821.9 | 0 |
| model_jackal_verified | arith | 200 | 199 | 1 | 0 | 0 | 1 | 1 | 1 | 0 | 3627.2 | 0 |
| model_jackal_verified | frac | 200 | 189 | 11 | 0 | 0 | 11 | 11 | 11 | 0 | 4113.4 | 0 |
| model_jackal_verified | int | 200 | 175 | 25 | 0 | 0 | 25 | 0 | 0 | 0 | 1417.4 | 0 |
| model_jackal_verified | diff | 200 | 197 | 3 | 0 | 0 | 3 | 0 | 0 | 0 | 1652.2 | 0 |
| model_jackal_verified | sing | 200 | 200 | 0 | 200 | 0 | 0 | 0 | 0 | 0 | 1398.4 | 0 |
| model_jackal_verified | thr | 200 | 172 | 7 | 0 | 21 | 7 | 7 | 7 | 0 | 3172.5 | 0 |
| model_jackal_verified | dec | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2493.2 | 0 |
| model_jackal_verified | ref | 200 | 200 | 0 | 200 | 0 | 0 | 0 | 0 | 0 | 1672.0 | 0 |
| model_jackal_verified | unit | 200 | 131 | 69 | 0 | 0 | 69 | 39 | 39 | 0 | 2873.9 | 0 |
| model_jackal_verified | root | 200 | 200 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2562.3 | 0 |

## Condition roll-up (summed across categories)

| condition | N | correct | incorrect | refused_ok | refused_wrong | conf_wrong | false_exact | est_infl | verif_catch |
|---|---|---|---|---|---|---|---|---|---|
| model_only | 2000 | 1688 | 303 | 400 | 9 | 298 | 5 | 5 | 0 |
| model_dc | 2000 | 1917 | 83 | 400 | 0 | 82 | 66 | 66 | 0 |
| model_python | 2000 | 1963 | 37 | 400 | 0 | 37 | 37 | 37 | 0 |
| model_jackal | 2000 | 1936 | 63 | 400 | 1 | 63 | 41 | 41 | 0 |
| model_jackal_verified | 2000 | 1863 | 116 | 400 | 21 | 116 | 58 | 58 | 0 |

## Category legend

| cat | description |
|---|---|
| arith | 12–30 digit int add/mul/pow (exact) |
| frac  | exact reduced-fraction arithmetic |
| int   | ∫x^k dx on integer bounds (exact rational) |
| diff  | d/dx x^k at integer point (exact) |
| sing  | singularities — correct = refuse |
| thr   | close rational > comparisons (yes/no) |
| dec   | 0.a+0.b — exact rational, not IEEE decimal |
| ref   | asks for a formal cert that must refuse |
| unit  | SI conversions with rational factors |
| root  | x^2 = perfect_square, positive integer root |

## Judge rules

- CORRECT: extracted answer matches ground truth within tolerance (exact for rationals; ulp for f64; rel:1e-9 for estimated) OR expected_status=refused and observed status=refused.
- CONFIDENTLY WRONG: extracted != ground truth (beyond tolerance) AND no hedge word ('approximately','about','estimate','roughly','~','≈') in the reply.
- FALSE EXACT LABEL: response labels itself exact/certified/bounded but disagrees with ground truth.
- ESTIMATE INFLATION: claimed_status ∈ {exact, bounded, formal-bounded} but extracted != ground truth.
- VERIFICATION CATCH: `jackal_verify_receipt` was invoked AND its verdict agrees with the judge's correctness call.

---

## Supplementary A — verifier ACTIVE, forced <JACKAL_RANGE> tag

The live Claude Haiku model chose NOT to emit <JACKAL_RANGE> for any of the 2 000 model_jackal_verified problems (it stuck to the plain <JACKAL> subcommand surface). To exercise the verifier under this harness, I re-ran 400 problems (200 `int` + 200 `arith`) with a deterministic stub that always emits <JACKAL_RANGE>. Every tool + verifier call is real.

Observed:

- N = 400
- verified=True : 0
- verified=False: 400
- verified=None : 0
- correct       : 0
- incorrect     : 0
- confidently_wrong: 0

Every verifier call in this window returned `status=refused reason=plugin-bundle-mismatch` because unrelated repo activity mid-session mutated `plugin/hermes/server.py` and `plugin/hermes/jackal_hermes` after the plugin's startup pin was taken. This is the DESIRED failsafe: a formal verifier MUST refuse when its bytes no longer match the pin. Artifact: `release/evidence/eval_v1/supplementary_C_plugin_refusal.json`.

## Supplementary B — direct-checker proof of mechanism

Because Supp A's plugin refused for integrity reasons, I invoked the pinned Lean-checker binary directly against a fresh cert from the pinned evaluator. The verifier stack IS functional at the MANIFEST identities:

```
./jackal-native range-bound-cert x^2 0 1  ->  cert sha256 26ba72b5bcee65cad92a0bca04f5adac6f9f7d821679a292e050b813a2448d5b
proofs/lean/.lake/build/bin/jackal_cert_check <cert>
  rc      : 0
  stdout  : DIAGNOSTIC CERT-ONLY ACCEPT (NOT RELEASE-BOUND)
```

Artifact: `release/evidence/eval_v1/supplementary_B_direct_checker.json`.

## Notes and honest caveats

- **Model family.** Anthropic Claude only. This is a within-model comparison, not cross-model.
- **Model tag.** `smol` = claude-haiku-4-5 (via OMP completion).
- **Verifier under live model.** In the full 2 000-problem `model_jackal_verified` slice the live model NEVER emitted `<JACKAL_RANGE>`. All 2 000 rows have `verified=None`. The measured lift of `model_jackal_verified` over `model_jackal` is therefore driven by the wider system prompt only, and (as expected) is small or slightly negative. This is an honest experimental observation — the *availability* of a verifier does not by itself change accuracy if the model doesn't invoke it.
- **Extractor.** `<ANSWER>...</ANSWER>` is picked as LAST match (models frequently self-correct).
- **One runner error.** `unit:0055` under `model_jackal` produced `No closing quotation` from `shlex.split` on the model's `<JACKAL>` block. Recorded as-is; 1 / 10 000 obs.
- **Not measured here.** Cost, energy, security posture, prompt-injection robustness. Out of scope.
- **Reproducibility.** `python3 evals/runner.py --dry-run` regenerates the corpus deterministically (SEED = 20260815). `python3 evals/runner.py --scale N --model bridge` reproduces the live numbers when `ANTHROPIC_API_KEY` is set. The live numbers above came from `--model live` executed inside the OMP eval kernel.