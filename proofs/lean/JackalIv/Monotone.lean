/-
JACKAL certified interval lane — the generic MONOTONE-FUNCTION rule.

Engine correspondence (jackal_calc.anb, section "JACKAL CERTIFIED INTERVAL
ENGINE", git 8a71540): the unary elementary functions

  iv_sqrt  (line 2315):  iv_out(sqrt(a.lo),  sqrt(a.hi))
  iv_cbrt  (line 2325):  iv_out(cbrt(a.lo),  cbrt(a.hi))
  iv_exp   (line 2330):  iv_out(exp(a.lo),   exp(a.hi))
  iv_ln    (line 2335):  iv_out(ln(a.lo),    ln(a.hi))
  iv_log10 (line 2341):  iv_out(log10(a.lo), log10(a.hi))
  iv_log2  (line 2347):  iv_out(log2(a.lo),  log2(a.hi))
  iv_asin  (line 2414):  iv_out(asin(a.lo),  asin(a.hi))
  iv_atan  (line 2426):  iv_out(atan(a.lo),  atan(a.hi))

all evaluate the platform libm function at the two interval endpoints and
outward-pad the results via iv_out, relying on monotonicity of the function
on the interval; the one antitone case is

  iv_acos  (line 2420):  iv_out(acos(a.hi), acos(a.lo))

which swaps the endpoints.  The theorems here mechanize exactly that rule:

* `iv_monotone_encloses` — the generic rule: if g is monotone on [a,b],
  fl_a / fl_b are libm evaluations of g at the endpoints (Approx δlib σ0),
  then for every x ∈ [a,b] the padded bracket [padLo fl_a, padHi fl_b]
  contains g x.  This is the soundness statement for every entry in the
  first list above.
* `iv_antitone_encloses` — the swapped-endpoint variant modelling iv_acos.
* `iv_exp_encloses`, `iv_sqrt_encloses`, `iv_log_encloses`,
  `iv_atan_encloses`, `iv_asin_encloses`, `iv_acos_encloses` — instances
  discharging the monotonicity hypothesis from Mathlib for the concrete
  libm functions the engine calls (Real.exp, Real.sqrt, Real.log,
  Real.arctan, Real.arcsin, Real.arccos).  iv_log10 / iv_log2 / iv_cbrt
  follow the same shape (log₁₀ = log / log 10 etc.); their monotonicity
  facts reduce to the same rule and are covered by the generic theorem.
-/
import JackalIv.Model
import JackalIv.Pad

namespace JackalIv

open Real Set

/-- Generic monotone rule (models iv_sqrt / iv_exp / iv_ln / iv_log10 /
iv_log2 / iv_atan / iv_asin / iv_cbrt): a function monotone on `[a,b]`,
evaluated by libm at the two endpoints and outward-padded, encloses the
exact image of every point of the interval. -/
theorem iv_monotone_encloses (g : ℝ → ℝ) (a b x fl_a fl_b : ℝ)
    (hmono : MonotoneOn g (Set.Icc a b))
    (hx : x ∈ Set.Icc a b) (hab : a ≤ b)
    (ha : Approx δlib σ0 fl_a (g a)) (hb : Approx δlib σ0 fl_b (g b)) :
    padLo fl_a ≤ g x ∧ g x ≤ padHi fl_b := by
  have haMem : a ∈ Set.Icc a b := ⟨le_refl a, hab⟩
  have hbMem : b ∈ Set.Icc a b := ⟨hab, le_refl b⟩
  have hga : g a ≤ g x := hmono haMem hx hx.1
  have hgb : g x ≤ g b := hmono hx hbMem hx.2
  have hlo : padLo fl_a ≤ g a := (libm_brackets fl_a (g a) ha).1
  have hhi : g b ≤ padHi fl_b := (libm_brackets fl_b (g b) hb).2
  exact ⟨le_trans hlo hga, le_trans hgb hhi⟩

/-- Generic antitone rule (models iv_acos, which evaluates at swapped
endpoints: iv_out(acos(a.hi), acos(a.lo))): the padded bracket is
`[padLo fl_b, padHi fl_a]`. -/
theorem iv_antitone_encloses (g : ℝ → ℝ) (a b x fl_a fl_b : ℝ)
    (hanti : AntitoneOn g (Set.Icc a b))
    (hx : x ∈ Set.Icc a b) (hab : a ≤ b)
    (ha : Approx δlib σ0 fl_a (g a)) (hb : Approx δlib σ0 fl_b (g b)) :
    padLo fl_b ≤ g x ∧ g x ≤ padHi fl_a := by
  have haMem : a ∈ Set.Icc a b := ⟨le_refl a, hab⟩
  have hbMem : b ∈ Set.Icc a b := ⟨hab, le_refl b⟩
  have hgb : g b ≤ g x := hanti hx hbMem hx.2
  have hga : g x ≤ g a := hanti haMem hx hx.1
  have hlo : padLo fl_b ≤ g b := (libm_brackets fl_b (g b) hb).1
  have hhi : g a ≤ padHi fl_a := (libm_brackets fl_a (g a) ha).2
  exact ⟨le_trans hlo hgb, le_trans hga hhi⟩

/-- iv_exp: `exp` is monotone everywhere, so the endpoint rule encloses. -/
theorem iv_exp_encloses (a b x fl_a fl_b : ℝ)
    (hx : x ∈ Set.Icc a b) (hab : a ≤ b)
    (ha : Approx δlib σ0 fl_a (Real.exp a))
    (hb : Approx δlib σ0 fl_b (Real.exp b)) :
    padLo fl_a ≤ Real.exp x ∧ Real.exp x ≤ padHi fl_b :=
  iv_monotone_encloses Real.exp a b x fl_a fl_b
    (fun _ _ _ _ h => Real.exp_le_exp.mpr h) hx hab ha hb

/-- iv_sqrt: `Real.sqrt` is monotone everywhere (0 on negatives). -/
theorem iv_sqrt_encloses (a b x fl_a fl_b : ℝ)
    (hx : x ∈ Set.Icc a b) (hab : a ≤ b)
    (ha : Approx δlib σ0 fl_a (Real.sqrt a))
    (hb : Approx δlib σ0 fl_b (Real.sqrt b)) :
    padLo fl_a ≤ Real.sqrt x ∧ Real.sqrt x ≤ padHi fl_b :=
  iv_monotone_encloses Real.sqrt a b x fl_a fl_b
    (fun _ _ _ _ h => Real.sqrt_le_sqrt h) hx hab ha hb

/-- iv_ln: `Real.log` is monotone on `[a,b]` once `0 < a` (the engine
guards `a.lo > 0` before calling `ln`). -/
theorem iv_log_encloses (a b x fl_a fl_b : ℝ)
    (hpos : 0 < a)
    (hx : x ∈ Set.Icc a b) (hab : a ≤ b)
    (ha : Approx δlib σ0 fl_a (Real.log a))
    (hb : Approx δlib σ0 fl_b (Real.log b)) :
    padLo fl_a ≤ Real.log x ∧ Real.log x ≤ padHi fl_b := by
  refine iv_monotone_encloses Real.log a b x fl_a fl_b ?_ hx hab ha hb
  intro u hu v hv huv
  have hu0 : 0 < u := lt_of_lt_of_le hpos hu.1
  have hv0 : 0 < v := lt_of_lt_of_le hpos hv.1
  exact (Real.log_le_log_iff hu0 hv0).mpr huv

/-- iv_atan: `Real.arctan` is monotone everywhere. -/
theorem iv_atan_encloses (a b x fl_a fl_b : ℝ)
    (hx : x ∈ Set.Icc a b) (hab : a ≤ b)
    (ha : Approx δlib σ0 fl_a (Real.arctan a))
    (hb : Approx δlib σ0 fl_b (Real.arctan b)) :
    padLo fl_a ≤ Real.arctan x ∧ Real.arctan x ≤ padHi fl_b :=
  iv_monotone_encloses Real.arctan a b x fl_a fl_b
    (Real.arctan_mono.monotoneOn _) hx hab ha hb

/-- iv_asin: `Real.arcsin` is monotone (globally, via projIcc); the engine
guards the domain to `[-1,1]`, recorded here as a hypothesis for fidelity. -/
theorem iv_asin_encloses (a b x fl_a fl_b : ℝ)
    (_hdom : -1 ≤ a ∧ b ≤ 1)
    (hx : x ∈ Set.Icc a b) (hab : a ≤ b)
    (ha : Approx δlib σ0 fl_a (Real.arcsin a))
    (hb : Approx δlib σ0 fl_b (Real.arcsin b)) :
    padLo fl_a ≤ Real.arcsin x ∧ Real.arcsin x ≤ padHi fl_b :=
  iv_monotone_encloses Real.arcsin a b x fl_a fl_b
    (Real.monotone_arcsin.monotoneOn _) hx hab ha hb

/-- iv_acos: `Real.arccos` is antitone, so the engine swaps endpoints
(iv_out(acos(a.hi), acos(a.lo))); the enclosure is `[padLo fl_b, padHi fl_a]`
where `fl_a` approximates `arccos a` and `fl_b` approximates `arccos b`. -/
theorem iv_acos_encloses (a b x fl_a fl_b : ℝ)
    (_hdom : -1 ≤ a ∧ b ≤ 1)
    (hx : x ∈ Set.Icc a b) (hab : a ≤ b)
    (ha : Approx δlib σ0 fl_a (Real.arccos a))
    (hb : Approx δlib σ0 fl_b (Real.arccos b)) :
    padLo fl_b ≤ Real.arccos x ∧ Real.arccos x ≤ padHi fl_a :=
  iv_antitone_encloses Real.arccos a b x fl_a fl_b
    (Real.antitone_arccos.antitoneOn _) hx hab ha hb

end JackalIv
