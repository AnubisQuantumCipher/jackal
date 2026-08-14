/-
JackalIv/CritIn.lean — conservativity of the engine's `crit_in` float test.

Engine correspondence (jackal_calc.anb, section "JACKAL CERTIFIED INTERVAL
ENGINE", fn `crit_in` line 2357, git 8a71540):

    fn crit_in(lo, hi, offset, period) {
        let slack = (abs(lo) + abs(hi)) * 1e-12 + 1e-12;      // line 2358
        let k = floor((lo - offset) / period) - 1;            // lines 2359-2360
        while step < 5 {                                      // k0-1 .. k0+3
            let cand = offset + (k + step) * period;          // line 2363
            if cand >= lo - slack && cand <= hi + slack { return true; }
        }
        return false;
    }

Callers guarantee `hi - lo < 2 * period` before calling (iv_sin/iv_cos refuse
at width ≥ 2π with period 2π; iv_tan refuses at width ≥ π with period π):

    iv_sin (lines 2380-2381): offsets  π/2 (1.5707963267948966) and -π/2,
                              period 2π (6.283185307179586)
    iv_cos (lines 2397-2398): offsets  0.0 and π (3.141592653589793),
                              period 2π
    iv_tan (line 2408):       offset   π/2, period π

Theorem → engine-line map:

| theorem                        | engine behaviour modeled                     |
|--------------------------------|----------------------------------------------|
| `crit_window_covers`           | the 5-candidate scan k0-1..k0+3 (2359-2366)  |
|                                | covers every k with offset+k·period ∈ [lo,hi]|
| `slack_admissible`             | the accept test `cand ≥ lo-slack ∧           |
|                                | cand ≤ hi+slack` (2364) catches any true     |
|                                | candidate whose float image drifted ≤ slack  |
| `crit_in_conservative`         | all 5 candidates rejected ⇒ NO true critical |
|                                | point offset+k·period lies in [lo,hi]        |
| `crit_in_conservative_pair`    | two families at once (the shape of the       |
|                                | `hcrit` hypotheses in Trig.lean)             |
| `crit_in_conservative_sin`     | iv_sin's two tests (2380-2381), conclusion   |
|                                | literally the `hcrit` of                     |
|                                | `iv_sin_encloses_no_crit` in Trig.lean       |
| `crit_in_conservative_cos`     | iv_cos's two tests (2397-2398), conclusion   |
|                                | literally the `hcrit` of                     |
|                                | `iv_cos_encloses_no_crit`                    |
| `crit_in_conservative_tan`     | iv_tan's pole test (2408)                    |
| `error_budget_dominated`       | the float evaluation of                      |
|                                | `offset + (k + step) * period` (2363): one   |
|                                | basic mul + one basic add (Approx δ0 σ0      |
|                                | each), times a π-derived period constant     |
|                                | within δlib relative of the real period,     |
|                                | stays within `slack` for the engine's        |
|                                | parameter range                              |
| `engine_candidate_within_slack`| error budget ⇒ the hypothesis of             |
|                                | `slack_admissible` holds, closing the chain  |

Engine parameter range covered by `error_budget_dominated`: offsets
0, ±π/2, π (all with |offset| ≤ 4), periods π and 2π (both within [1, 7]).
The small integer `k + step` (a handful of periods around [lo, hi]) is exact
in float — IEEE-754 represents it exactly — so only the mul, the add, and
the period constant itself carry error, which is what the lemma budgets.

Claims discipline: all statements are about the model in `JackalIv.Model`.
`error_budget_dominated` turns Trig.lean's previously *assumed* `crit_in`
conservativity into a theorem OF THE MODEL, conditional on the disclosed
Approx-model hypotheses about the two basic float ops and the π-derived
period constant. The gap between this model and the shipped float code
remains the disclosed residual recorded in Ledger.lean.
-/
import JackalIv.Model

namespace JackalIv

open Real

/-- The engine's slack (`crit_in` line 2358):
`(abs(lo) + abs(hi)) * 1e-12 + 1e-12`. -/
noncomputable def slackR (lo hi : ℝ) : ℝ := (|lo| + |hi|) * (1 / 10 ^ 12) + 1 / 10 ^ 12

/-- The engine's window base (`crit_in` line 2359):
`k0 = floor((lo - offset) / period)`. -/
noncomputable def critK0 (lo offset period : ℝ) : ℤ := ⌊(lo - offset) / period⌋

lemma slackR_pos (lo hi : ℝ) : 0 < slackR lo hi := by
  unfold slackR
  positivity

/-! ### 1. The 5-candidate window covers every true critical point -/

/-- `crit_in`'s scan window is complete: for `period > 0` and interval width
`< 2 * period` (guaranteed by all three callers), every integer `k` with
`offset + k * period ∈ [lo, hi]` satisfies `k0 - 1 ≤ k ≤ k0 + 3` where
`k0 = ⌊(lo - offset) / period⌋` — so the engine's loop over
`{k0-1, …, k0+3}` (lines 2360–2366) never misses a true critical point. -/
theorem crit_window_covers (lo hi offset period : ℝ) (k : ℤ)
    (hper : 0 < period) (hwidth : hi - lo < 2 * period)
    (hmem : offset + (k : ℝ) * period ∈ Set.Icc lo hi) :
    critK0 lo offset period - 1 ≤ k ∧ k ≤ critK0 lo offset period + 3 := by
  unfold critK0
  obtain ⟨h1, h2⟩ := hmem
  have hfl : ((⌊(lo - offset) / period⌋ : ℤ) : ℝ) ≤ (lo - offset) / period :=
    Int.floor_le _
  have hfu : (lo - offset) / period < ((⌊(lo - offset) / period⌋ : ℤ) : ℝ) + 1 :=
    Int.lt_floor_add_one _
  -- lower: lo ≤ offset + k·period gives (lo - offset)/period ≤ k, so k0 ≤ k
  have hlo : (lo - offset) / period ≤ (k : ℝ) := by
    rw [div_le_iff₀ hper]
    linarith
  have hklo : ⌊(lo - offset) / period⌋ ≤ k := by
    have h : ((⌊(lo - offset) / period⌋ : ℤ) : ℝ) ≤ (k : ℝ) := le_trans hfl hlo
    exact_mod_cast h
  -- upper: k·period ≤ hi - offset < 2·period + (lo - offset) < (k0 + 3)·period
  have hup : lo - offset < (((⌊(lo - offset) / period⌋ : ℤ) : ℝ) + 1) * period :=
    (div_lt_iff₀ hper).mp hfu
  have hkub : (k : ℝ) * period <
      (((⌊(lo - offset) / period⌋ : ℤ) : ℝ) + 3) * period := by
    nlinarith [h2, hwidth, hup]
  have hkR : (k : ℝ) < ((⌊(lo - offset) / period⌋ : ℤ) : ℝ) + 3 :=
    lt_of_mul_lt_mul_right hkub hper.le
  have hk3 : k < ⌊(lo - offset) / period⌋ + 3 := by exact_mod_cast hkR
  exact ⟨by omega, by omega⟩

/-! ### 2. The slack-widened accept test is a sound bridge -/

/-- The bridge `crit_in` relies on (accept test, line 2364): if the computed
candidate `candF` drifted from the true candidate `cand` by at most the
engine slack, then a true candidate inside `[lo, hi]` forces `candF` inside
the slack-widened test window `[lo - slack, hi + slack]` — i.e. the test
CANNOT reject it. -/
theorem slack_admissible (lo hi cand candF : ℝ)
    (herr : |candF - cand| ≤ slackR lo hi)
    (hmem : cand ∈ Set.Icc lo hi) :
    lo - slackR lo hi ≤ candF ∧ candF ≤ hi + slackR lo hi := by
  obtain ⟨h1, h2⟩ := hmem
  obtain ⟨e1, e2⟩ := abs_le.mp herr
  exact ⟨by linarith, by linarith⟩

/-! ### 3. Conservativity: all candidates rejected ⇒ no true critical point -/

/-- Conservativity of `crit_in`, parameterized by `offset`/`period` so one
theorem serves iv_sin, iv_cos and iv_tan: if for every window index
`k ∈ {k0-1, …, k0+3}` the computed candidate `candF k` was within slack of
the true candidate (the error-budget hypothesis, discharged for the engine's
parameters by `error_budget_dominated`) and was REJECTED by the accept test
(`candF k < lo - slack ∨ candF k > hi + slack`), then NO true critical point
`offset + k * period` lies in `[lo, hi]`.  The conclusion is the exact
normal form Trig.lean's `hcrit`/`hmin`/`hmax` hypotheses take. -/
theorem crit_in_conservative (lo hi offset period : ℝ) (candF : ℤ → ℝ)
    (hper : 0 < period) (hwidth : hi - lo < 2 * period)
    (herr : ∀ k : ℤ, critK0 lo offset period - 1 ≤ k →
      k ≤ critK0 lo offset period + 3 →
      |candF k - (offset + (k : ℝ) * period)| ≤ slackR lo hi)
    (hrej : ∀ k : ℤ, critK0 lo offset period - 1 ≤ k →
      k ≤ critK0 lo offset period + 3 →
      candF k < lo - slackR lo hi ∨ hi + slackR lo hi < candF k) :
    ∀ k : ℤ, offset + (k : ℝ) * period ∉ Set.Icc lo hi := by
  intro k hmem
  obtain ⟨hk1, hk2⟩ := crit_window_covers lo hi offset period k hper hwidth hmem
  obtain ⟨hc1, hc2⟩ :=
    slack_admissible lo hi (offset + (k : ℝ) * period) (candF k)
      (herr k hk1 hk2) hmem
  rcases hrej k hk1 hk2 with h | h
  · linarith
  · linarith

/-- Two `crit_in` families at once — the paired shape of the `hcrit`
hypothesis taken by `iv_sin_encloses_no_crit` / `iv_cos_encloses_no_crit`
in Trig.lean. -/
theorem crit_in_conservative_pair (lo hi off₁ off₂ period : ℝ)
    (candF₁ candF₂ : ℤ → ℝ)
    (hper : 0 < period) (hwidth : hi - lo < 2 * period)
    (herr₁ : ∀ k : ℤ, critK0 lo off₁ period - 1 ≤ k →
      k ≤ critK0 lo off₁ period + 3 →
      |candF₁ k - (off₁ + (k : ℝ) * period)| ≤ slackR lo hi)
    (hrej₁ : ∀ k : ℤ, critK0 lo off₁ period - 1 ≤ k →
      k ≤ critK0 lo off₁ period + 3 →
      candF₁ k < lo - slackR lo hi ∨ hi + slackR lo hi < candF₁ k)
    (herr₂ : ∀ k : ℤ, critK0 lo off₂ period - 1 ≤ k →
      k ≤ critK0 lo off₂ period + 3 →
      |candF₂ k - (off₂ + (k : ℝ) * period)| ≤ slackR lo hi)
    (hrej₂ : ∀ k : ℤ, critK0 lo off₂ period - 1 ≤ k →
      k ≤ critK0 lo off₂ period + 3 →
      candF₂ k < lo - slackR lo hi ∨ hi + slackR lo hi < candF₂ k) :
    ∀ k : ℤ, (off₁ + (k : ℝ) * period) ∉ Set.Icc lo hi ∧
             (off₂ + (k : ℝ) * period) ∉ Set.Icc lo hi :=
  fun k =>
    ⟨crit_in_conservative lo hi off₁ period candF₁ hper hwidth herr₁ hrej₁ k,
     crit_in_conservative lo hi off₂ period candF₂ hper hwidth herr₂ hrej₂ k⟩

/-- iv_sin's two `crit_in` calls (lines 2380–2381: offsets `π/2` and `-π/2`,
period `2π`): if both scans rejected every candidate, no sin extremum lies in
`[a, b]`.  The conclusion is literally the `hcrit` hypothesis of
`iv_sin_encloses_no_crit` / `iv_sin_encloses_no_crit_clamped` in Trig.lean. -/
theorem crit_in_conservative_sin {a b : ℝ} (candFmax candFmin : ℤ → ℝ)
    (hwidth : b - a < 2 * (2 * π))
    (herrMax : ∀ k : ℤ, critK0 a (π / 2) (2 * π) - 1 ≤ k →
      k ≤ critK0 a (π / 2) (2 * π) + 3 →
      |candFmax k - (π / 2 + (k : ℝ) * (2 * π))| ≤ slackR a b)
    (hrejMax : ∀ k : ℤ, critK0 a (π / 2) (2 * π) - 1 ≤ k →
      k ≤ critK0 a (π / 2) (2 * π) + 3 →
      candFmax k < a - slackR a b ∨ b + slackR a b < candFmax k)
    (herrMin : ∀ k : ℤ, critK0 a (-(π / 2)) (2 * π) - 1 ≤ k →
      k ≤ critK0 a (-(π / 2)) (2 * π) + 3 →
      |candFmin k - (-(π / 2) + (k : ℝ) * (2 * π))| ≤ slackR a b)
    (hrejMin : ∀ k : ℤ, critK0 a (-(π / 2)) (2 * π) - 1 ≤ k →
      k ≤ critK0 a (-(π / 2)) (2 * π) + 3 →
      candFmin k < a - slackR a b ∨ b + slackR a b < candFmin k) :
    ∀ k : ℤ, (π / 2 + (k : ℝ) * (2 * π)) ∉ Set.Icc a b ∧
             (-(π / 2) + (k : ℝ) * (2 * π)) ∉ Set.Icc a b := by
  have hper : (0 : ℝ) < 2 * π := by positivity
  exact crit_in_conservative_pair a b (π / 2) (-(π / 2)) (2 * π)
    candFmax candFmin hper hwidth herrMax hrejMax herrMin hrejMin

/-- iv_cos's two `crit_in` calls (lines 2397–2398: offsets `0` and `π`,
period `2π`).  The conclusion is literally the `hcrit` hypothesis of
`iv_cos_encloses_no_crit` / `iv_cos_encloses_no_crit_clamped` in Trig.lean
(the maximizer family `k·2π` is offset `0` with the `0 +` normalized away). -/
theorem crit_in_conservative_cos {a b : ℝ} (candFmax candFmin : ℤ → ℝ)
    (hwidth : b - a < 2 * (2 * π))
    (herrMax : ∀ k : ℤ, critK0 a 0 (2 * π) - 1 ≤ k →
      k ≤ critK0 a 0 (2 * π) + 3 →
      |candFmax k - (k : ℝ) * (2 * π)| ≤ slackR a b)
    (hrejMax : ∀ k : ℤ, critK0 a 0 (2 * π) - 1 ≤ k →
      k ≤ critK0 a 0 (2 * π) + 3 →
      candFmax k < a - slackR a b ∨ b + slackR a b < candFmax k)
    (herrMin : ∀ k : ℤ, critK0 a π (2 * π) - 1 ≤ k →
      k ≤ critK0 a π (2 * π) + 3 →
      |candFmin k - (π + (k : ℝ) * (2 * π))| ≤ slackR a b)
    (hrejMin : ∀ k : ℤ, critK0 a π (2 * π) - 1 ≤ k →
      k ≤ critK0 a π (2 * π) + 3 →
      candFmin k < a - slackR a b ∨ b + slackR a b < candFmin k) :
    ∀ k : ℤ, ((k : ℝ) * (2 * π)) ∉ Set.Icc a b ∧
             (π + (k : ℝ) * (2 * π)) ∉ Set.Icc a b := by
  have hper : (0 : ℝ) < 2 * π := by positivity
  intro k
  constructor
  · have h := crit_in_conservative a b 0 (2 * π) candFmax hper hwidth
      (fun k hk1 hk2 => by
        simp only [zero_add]
        exact herrMax k hk1 hk2)
      hrejMax k
    simp only [zero_add] at h
    exact h
  · exact crit_in_conservative a b π (2 * π) candFmin hper hwidth
      herrMin hrejMin k

/-- iv_tan's `crit_in` call (line 2408: offset `π/2`, period `π`): all
candidates rejected ⇒ no tan pole `π/2 + kπ` lies in `[a, b]`, so the
engine's decision NOT to refuse was sound. -/
theorem crit_in_conservative_tan {a b : ℝ} (candF : ℤ → ℝ)
    (hwidth : b - a < 2 * π)
    (herr : ∀ k : ℤ, critK0 a (π / 2) π - 1 ≤ k → k ≤ critK0 a (π / 2) π + 3 →
      |candF k - (π / 2 + (k : ℝ) * π)| ≤ slackR a b)
    (hrej : ∀ k : ℤ, critK0 a (π / 2) π - 1 ≤ k → k ≤ critK0 a (π / 2) π + 3 →
      candF k < a - slackR a b ∨ b + slackR a b < candF k) :
    ∀ k : ℤ, (π / 2 + (k : ℝ) * π) ∉ Set.Icc a b :=
  crit_in_conservative a b (π / 2) π candF Real.pi_pos hwidth herr hrej

/-! ### 4. The error budget: the slack dominates the candidate's float error -/

set_option exponentiation.threshold 2000 in
private lemma σ0_le_small : σ0 ≤ 1 / 10 ^ 15 := by
  unfold σ0
  rw [div_le_div_iff₀ (by positivity) (by positivity)]
  norm_num

private lemma δ0_le_small : δ0 ≤ 1 / 10 ^ 15 := by
  unfold δ0
  rw [div_le_div_iff₀ (by positivity) (by positivity)]
  norm_num

private lemma δlib_le_small : δlib ≤ 1 / 10 ^ 15 := by
  unfold δlib
  rw [div_le_div_iff₀ (by positivity) (by positivity)]
  norm_num

/-- The Approx-model error of the engine's candidate computation
`offset + (k + step) * period` (`crit_in` line 2363) is dominated by the
engine slack, for the engine's actual parameter range: offsets 0, ±π/2, π
(all `|offset| ≤ 4`), periods π and 2π (both in `[1, 7]`).

Error model, hypothesis for hypothesis:
* the period constant is π-derived, within δlib relative of the real period
  (`|periodF - period| ≤ δlib * period`);
* the integer multiplier `m = k + step` is exact in float and window-bounded
  (`|m| ≤ (|lo| + |hi|)/period + 3`);
* one basic mul (`Approx δ0 σ0 mulF (m * periodF)`) and
  one basic add (`Approx δ0 σ0 candF (offset + mulF)`).

Conclusion: `|candF - (offset + m*period)| ≤ slackR lo hi` — exactly the
`herr` hypothesis of `slack_admissible` / `crit_in_conservative`.  (Total
budget ≈ 7·10⁻¹⁵·(|lo|+|hi|) + 1.6·10⁻¹³, versus slack
10⁻¹²·(|lo|+|hi|) + 10⁻¹² — three orders of margin.) -/
theorem error_budget_dominated
    (lo hi offset period periodF mulF candF : ℝ) (m : ℤ)
    (hper1 : 1 ≤ period) (hper7 : period ≤ 7)
    (hoff : |offset| ≤ 4)
    (hpF : |periodF - period| ≤ δlib * period)
    (hm : |(m : ℝ)| ≤ (|lo| + |hi|) / period + 3)
    (hmul : Approx δ0 σ0 mulF ((m : ℝ) * periodF))
    (hadd : Approx δ0 σ0 candF (offset + mulF)) :
    |candF - (offset + (m : ℝ) * period)| ≤ slackR lo hi := by
  unfold slackR
  set A := |lo| + |hi| with hAdef
  have hA0 : (0 : ℝ) ≤ A := by rw [hAdef]; positivity
  have hper0 : (0 : ℝ) < period := lt_of_lt_of_le one_pos hper1
  have hδ0e : δ0 ≤ 1 / 10 ^ 15 := δ0_le_small
  have hδlibe : δlib ≤ 1 / 10 ^ 15 := δlib_le_small
  have hσ0e : σ0 ≤ 1 / 10 ^ 15 := σ0_le_small
  have hδ01 : δ0 ≤ 1 := le_trans hδ0e (by norm_num)
  have hδlib1 : δlib ≤ 1 := le_trans hδlibe (by norm_num)
  have hσ01 : σ0 ≤ 1 := le_trans hσ0e (by norm_num)
  -- |m| · period ≤ A + 21 (window bound × period ∈ [1,7])
  have hmp : |(m : ℝ)| * period ≤ A + 21 := by
    have h1 : |(m : ℝ)| * period ≤ (A / period + 3) * period :=
      mul_le_mul_of_nonneg_right hm hper0.le
    have h2 : (A / period + 3) * period = A + 3 * period := by
      rw [add_mul, div_mul_cancel₀ A hper0.ne']
    rw [h2] at h1
    linarith
  have habs_mp : |(m : ℝ) * period| = |(m : ℝ)| * period := by
    rw [abs_mul, abs_of_pos hper0]
  -- period-constant drift: |m·periodF − m·period| ≤ δlib·(A + 21)
  have hdrift : |(m : ℝ) * periodF - (m : ℝ) * period| ≤ δlib * (A + 21) := by
    have h1 : (m : ℝ) * periodF - (m : ℝ) * period
        = (m : ℝ) * (periodF - period) := by ring
    rw [h1, abs_mul]
    calc |(m : ℝ)| * |periodF - period|
        ≤ |(m : ℝ)| * (δlib * period) :=
          mul_le_mul_of_nonneg_left hpF (abs_nonneg _)
      _ = δlib * (|(m : ℝ)| * period) := by ring
      _ ≤ δlib * (A + 21) := mul_le_mul_of_nonneg_left hmp δlib_pos.le
  -- |m·periodF| ≤ 2A + 42
  have hMPF : |(m : ℝ) * periodF| ≤ 2 * A + 42 := by
    have h1 : |(m : ℝ) * periodF| ≤
        |(m : ℝ) * period| + |(m : ℝ) * periodF - (m : ℝ) * period| := by
      calc |(m : ℝ) * periodF|
          = |(m : ℝ) * period + ((m : ℝ) * periodF - (m : ℝ) * period)| := by
            congr 1; ring
        _ ≤ _ := abs_add_le _ _
    have h2 : |(m : ℝ) * period| ≤ A + 21 := by rw [habs_mp]; exact hmp
    have h3 : δlib * (A + 21) ≤ A + 21 := by nlinarith [hA0, hδlib1]
    linarith
  -- the basic mul: |mulF − m·periodF| ≤ δ0·(2A + 42) + σ0
  have hmul' : |mulF - (m : ℝ) * periodF| ≤ δ0 * (2 * A + 42) + σ0 := by
    have h : |mulF - (m : ℝ) * periodF| ≤ δ0 * |(m : ℝ) * periodF| + σ0 := hmul
    have h2 : δ0 * |(m : ℝ) * periodF| ≤ δ0 * (2 * A + 42) :=
      mul_le_mul_of_nonneg_left hMPF δ0_pos.le
    linarith
  -- |mulF| ≤ 4A + 85, hence |offset + mulF| ≤ 4A + 89
  have hMulF : |mulF| ≤ 4 * A + 85 := by
    have h1 : |mulF| ≤ |(m : ℝ) * periodF| + |mulF - (m : ℝ) * periodF| := by
      calc |mulF| = |(m : ℝ) * periodF + (mulF - (m : ℝ) * periodF)| := by
            congr 1; ring
        _ ≤ _ := abs_add_le _ _
    have h2 : δ0 * (2 * A + 42) ≤ 2 * A + 42 := by nlinarith [hA0, hδ01]
    linarith
  have hOffMul : |offset + mulF| ≤ 4 * A + 89 := by
    calc |offset + mulF| ≤ |offset| + |mulF| := abs_add_le _ _
      _ ≤ 4 + (4 * A + 85) := add_le_add hoff hMulF
      _ = 4 * A + 89 := by ring
  -- the basic add: |candF − (offset + mulF)| ≤ δ0·(4A + 89) + σ0
  have hadd' : |candF - (offset + mulF)| ≤ δ0 * (4 * A + 89) + σ0 := by
    have h : |candF - (offset + mulF)| ≤ δ0 * |offset + mulF| + σ0 := hadd
    have h2 : δ0 * |offset + mulF| ≤ δ0 * (4 * A + 89) :=
      mul_le_mul_of_nonneg_left hOffMul δ0_pos.le
    linarith
  -- triangle: add error + mul error + period-constant drift
  have htri : |candF - (offset + (m : ℝ) * period)| ≤
      |candF - (offset + mulF)| + |mulF - (m : ℝ) * periodF| +
      |(m : ℝ) * periodF - (m : ℝ) * period| := by
    have h2 := abs_add_le (mulF - (m : ℝ) * periodF)
      ((m : ℝ) * periodF - (m : ℝ) * period)
    have h1 : |candF - (offset + (m : ℝ) * period)| ≤
        |candF - (offset + mulF)| +
        |(mulF - (m : ℝ) * periodF) + ((m : ℝ) * periodF - (m : ℝ) * period)| := by
      calc |candF - (offset + (m : ℝ) * period)|
          = |(candF - (offset + mulF)) +
              ((mulF - (m : ℝ) * periodF) +
                ((m : ℝ) * periodF - (m : ℝ) * period))| := by
            congr 1; ring
        _ ≤ _ := abs_add_le _ _
    linarith
  -- close out numerically: total ≤ (7A + 154)·10⁻¹⁵ ≤ A·10⁻¹² + 10⁻¹²
  have hb1 : δ0 * (4 * A + 89) ≤ (1 / 10 ^ 15) * (4 * A + 89) :=
    mul_le_mul_of_nonneg_right hδ0e (by linarith)
  have hb2 : δ0 * (2 * A + 42) ≤ (1 / 10 ^ 15) * (2 * A + 42) :=
    mul_le_mul_of_nonneg_right hδ0e (by linarith)
  have hb3 : δlib * (A + 21) ≤ (1 / 10 ^ 15) * (A + 21) :=
    mul_le_mul_of_nonneg_right hδlibe (by linarith)
  nlinarith [htri, hadd', hmul', hdrift, hb1, hb2, hb3, hσ0e, hA0]

/-- Closing the chain for the engine's parameter range: under the error
budget of `error_budget_dominated`, a true critical point inside `[lo, hi]`
forces the computed candidate inside the slack-widened accept window — the
hypothesis of `slack_admissible` holds, so `crit_in` CANNOT miss it. -/
theorem engine_candidate_within_slack
    (lo hi offset period periodF mulF candF : ℝ) (m : ℤ)
    (hper1 : 1 ≤ period) (hper7 : period ≤ 7)
    (hoff : |offset| ≤ 4)
    (hpF : |periodF - period| ≤ δlib * period)
    (hm : |(m : ℝ)| ≤ (|lo| + |hi|) / period + 3)
    (hmul : Approx δ0 σ0 mulF ((m : ℝ) * periodF))
    (hadd : Approx δ0 σ0 candF (offset + mulF))
    (hmem : offset + (m : ℝ) * period ∈ Set.Icc lo hi) :
    lo - slackR lo hi ≤ candF ∧ candF ≤ hi + slackR lo hi :=
  slack_admissible lo hi (offset + (m : ℝ) * period) candF
    (error_budget_dominated lo hi offset period periodF mulF candF m
      hper1 hper7 hoff hpF hm hmul hadd) hmem

end JackalIv
