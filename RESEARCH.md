# JACKAL 10× Research Matrix

There is no objective single “world’s best calculator”; the official product pages show that leading products optimize different jobs.[1][2][3]
This matrix uses official product pages as the baseline rather than review-site rankings.[1][2][3]

| Baseline | Observed strengths | JACKAL response |
|---|---|---|
| TI-Nspire CX II CAS | Linked algebraic/graphical/numeric views; CAS; matrices; regression, distributions, hypothesis tests; saved documents; programming and sensor data.[1] | Add matrices, numerical solvers, model cards, and reproducible fingerprints. A terminal Anubis program cannot honestly claim equivalent interactive graphing or CAS. |
| Qalculate! | "Arbitrary precision with both rational and floating point numbers"; exact/approximate forms; symbolic calculus; "propagation of uncertainty and interval arithmetic"; extensive units/constants; plotting.[2] | Add first-class measured quantities, propagated uncertainty, dimensional checks, numerical calculus, and explicit model limits. JACKAL now implements exact arbitrary-precision **integers** (`big-add/mul/pow/fact/ncr`) and exact **big rationals** (`rat`) in pure Anubis, plus outward-rounded **interval arithmetic** as a certified lane (`integrate-bound`/`range-bound`, refuse-on-doubt — with its f64/libm rounding model stated rather than implied); arbitrary-precision floats and general CAS remain outside the claimed surface. |
| Soulver | Natural-language notepad; variables, line references, live updates, units, dates and scenario worksheets.[3] | Add human-readable calculation cards and Anubis-native audit narratives. JACKAL now has single-invocation worksheets with persistent variables (`worksheet "a = 5; b = a^2; a+b"`); a persistent reactive notebook with live updates is still not claimed. |
| SpeedCrunch | Fast keyboard workflow; live results/history; custom functions/variables; "up to 50 digits of precision"; formula/constants library.[4] | Keep a scriptable CLI, add domain models and self-auditing output. JACKAL's `big-` integer lane is exact at any length within stated compute caps (verified against Python's arbitrary precision, e.g. 1000! at 2568 digits) — beyond 50 digits for integer work. Float work remains IEEE-754 f64: 50-digit float precision is still not claimed. |

## Product thesis

JACKAL should not imitate button count; the baseline already spans linked representations, CAS, uncertainty, units, notebooks, history and user-defined functions.[1][2][3]
Its differentiated category is **claim-aware computation**:[unverified]

1. Every advanced model can state assumptions and applicability.
2. Measured quantities carry absolute and relative uncertainty.
3. Numerical answers can expose residual/error and sensitivity.
4. Unit conversions fail closed across unsupported dimensions.
5. Calculation cards carry deterministic SHA-256 fingerprints over canonical inputs and model identity.
6. All product logic and executable invariants remain in Anubis.
7. General expression evaluation (tokenizer/parser/evaluator in Anubis) with an explicit grammar,
   fail-closed parse errors, and numeric methods (Simpson, central difference, bisection) that
   report grid-refinement error estimates alongside every answer.

## The AI-era thesis: why the last calculator

The deepest reason a calculator still matters is that language models are structurally bad at
being one, and the production paradigm is delegation to deterministic engines:

1. OpenAI's GSM8K repository states "our models frequently fail to accurately perform
   calculations" and mitigates by training models to call a calculator.[5] The underlying paper
   reports state-of-the-art models "still struggle to robustly perform multi-step mathematical
   reasoning."[6]
2. Transformers solve multi-digit arithmetic by linearized subgraph matching, not systematic
   computation — a structural limitation, not an error rate to be trained away.[7]
3. Program-aided delegation (LLM decomposes, deterministic runtime computes) beat chain-of-thought
   PaLM-540B by 15 absolute points on GSM8K.[8] Models can teach themselves to call calculator
   APIs.[9] Structured tool use is a first-class production interface with schema-enforced
   arguments.[10]

Therefore the calculator worth building for this era is a **trustworthy tool endpoint**:
deterministic and replayable, exactness-flagged, error-quantified, echoing its parsed canonical
form (the dominant model-tool failure is transcription, not computation), and fail-closed with
typed errors. JACKAL's claim cards, `rat` exact/approx split, Richardson estimates, certified
interval enclosures (`integrate-bound`), numerically-checked `diff`, per-command epistemic
grades (`maturity`), and named-refusal panics are those properties, implemented.

## Sources

[1] https://education.ti.com/en/products/calculators/graphing-calculators/ti-nspire-cx-ii-cx-ii-cas — TI-Nspire CX II/CAS official product page
[2] https://qalculate.github.io/features.html — Qalculate! official features (arbitrary precision with rational and floating point numbers; interval arithmetic)
[3] https://soulver.app — Soulver official product page
[4] https://speedcrunch.org — SpeedCrunch official product page (up to 50 digits of precision)
[5] https://github.com/openai/grade-school-math — GSM8K README, OpenAI
[6] https://arxiv.org/abs/2110.14168 — Cobbe et al. 2021, Training Verifiers to Solve Math Word Problems
[7] https://arxiv.org/abs/2305.18654 — Dziri et al. 2023, Faith and Fate: Limits of Transformers on Compositionality
[8] https://arxiv.org/abs/2211.10435 — Gao et al. 2022, PAL: Program-aided Language Models
[9] https://arxiv.org/abs/2302.04761 — Schick et al. 2023, Toolformer
[10] https://platform.claude.com/docs/en/docs/agents-and-tools/tool-use/overview — Anthropic tool-use documentation
