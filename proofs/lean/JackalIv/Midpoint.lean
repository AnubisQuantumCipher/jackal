/-
JACKAL certified interval lane — the padded-midpoint theorems.

Engine correspondence (`jackal_calc.anb`, section "JACKAL CERTIFIED
INTEGRATION", fn `bound_step`, git 8a71540):

The Taylor-2/Taylor-4 forms in `bound_step` cancel their odd terms about the
EXACT real midpoint c = (a+b)/2 of a subinterval, but the engine can only
compute the float `m = fl((a+b)/2)` — one correctly rounded addition
followed by an EXACT halving (division by 2 is exact in binary floating
point away from underflow; the model covers the underflow tail with the σ0
absolute term).  The fix (adversarial review 2026-08-13) evaluates all
midpoint terms over the outward-padded interval `mI = iv_out(m, m) =
[padLo m, padHi m]` instead of the point `m`.  This file mechanizes why
that is sound:

* `half_exact_approx`      — models `m = s / 2.0` where `s = fl(a+b)`:
  an (δ0, σ0)-approximation of `a+b`, halved exactly, is an
  (δ0, σ0)-approximation of the exact midpoint `(a+b)/2`.
  (Halving scales both the error and the reference: δ0·|a+b|/2 =
  δ0·|(a+b)/2|, and σ0/2 ≤ σ0.)
* `exact_midpoint_in_padded` — models `mI = iv_out(m, m)`: the padded
  interval around the computed midpoint contains the exact real midpoint.
  This is the containment `c ∈ [padLo m, padHi m]` that `bound_step`'s
  comment asserts ("which provably contains c").
* `float_midpoint_in_padded` — the two composed: from the raw rounded sum
  straight to the containment `bound_step` needs.
* `midpoint_enclosure_transfer` — models `Fm = ieval(f, mI.lo, mI.hi)`:
  any enclosure of f over the padded midpoint interval bounds the exact
  value `f(c)` used by the Taylor forms (and likewise `F2m` for f'').
* `taylor_constants_check` block — the four integral identities behind the
  engine's hard-coded constants: over [a, b] with c = (a+b)/2,
    ∫ (x-c)^1 = 0            (odd term drops),
    ∫ (x-c)^2 = (b-a)^3/12   (→ h^3/24 after the 1/2! Taylor factor),
    ∫ (x-c)^3 = 0            (odd term drops),
    ∫ (x-c)^4 = (b-a)^5/80   (→ h^5/1920 after the 1/4! Taylor factor).
-/
import JackalIv.Model
import JackalIv.Pad

namespace JackalIv

/-! ## The exact-halving step -/

/-- Engine: `let m = (a_edge + b_edge) / 2.0` in `bound_step`.  The sum is
one rounded basic op (`Approx δ0 σ0 s (a+b)`); dividing by 2 is exact in
binary floating point, so `s/2` still (δ0, σ0)-approximates the exact
midpoint `(a+b)/2`. -/
theorem half_exact_approx (a b s : ℝ) (h : Approx δ0 σ0 s (a + b)) :
    Approx δ0 σ0 (s / 2) ((a + b) / 2) := by
  unfold Approx at h ⊢
  have habs : |s / 2 - (a + b) / 2| = |s - (a + b)| / 2 := by
    rw [div_sub_div_same, abs_div]
    norm_num
  have hhalf : |(a + b) / 2| = |a + b| / 2 := by
    rw [abs_div]; norm_num
  have hσ : σ0 / 2 ≤ σ0 := by linarith [σ0_pos]
  calc |s / 2 - (a + b) / 2| = |s - (a + b)| / 2 := habs
    _ ≤ (δ0 * |a + b| + σ0) / 2 := by linarith
    _ = δ0 * (|a + b| / 2) + σ0 / 2 := by ring
    _ = δ0 * |(a + b) / 2| + σ0 / 2 := by rw [hhalf]
    _ ≤ δ0 * |(a + b) / 2| + σ0 := by linarith

/-! ## The padded midpoint interval contains the exact midpoint -/

/-- Engine: `let mI = iv_out(m, m)` in `bound_step`.  The outward-padded
interval around the computed float midpoint contains the exact real
midpoint c = (a+b)/2.  Direct instantiation of `basic_brackets`. -/
theorem exact_midpoint_in_padded (a b m : ℝ)
    (h : Approx δ0 σ0 m ((a + b) / 2)) :
    padLo m ≤ (a + b) / 2 ∧ (a + b) / 2 ≤ padHi m :=
  basic_brackets m ((a + b) / 2) h

/-- The two composed: from the rounded sum `s = fl(a+b)` straight to the
containment `c ∈ [padLo (s/2), padHi (s/2)]` that `bound_step` relies on. -/
theorem float_midpoint_in_padded (a b s : ℝ) (h : Approx δ0 σ0 s (a + b)) :
    padLo (s / 2) ≤ (a + b) / 2 ∧ (a + b) / 2 ≤ padHi (s / 2) :=
  exact_midpoint_in_padded a b (s / 2) (half_exact_approx a b s h)

/-! ## Enclosure transfer through the padded midpoint -/

/-- Engine: `let Fm = ieval(f, mI.lo, mI.hi)` in `bound_step` (and likewise
`F2m` for f'').  Any interval `I` enclosing the image of `f` over the
padded midpoint interval bounds the exact midpoint value `f((a+b)/2)` the
Taylor forms are actually about. -/
theorem midpoint_enclosure_transfer (f : ℝ → ℝ) (I : IBox) (a b m : ℝ)
    (hEnc : Encloses I (f '' Set.Icc (padLo m) (padHi m)))
    (hm : Approx δ0 σ0 m ((a + b) / 2)) :
    I.lo ≤ f ((a + b) / 2) ∧ f ((a + b) / 2) ≤ I.hi := by
  obtain ⟨hlo, hhi⟩ := exact_midpoint_in_padded a b m hm
  exact hEnc (f ((a + b) / 2)) ⟨(a + b) / 2, ⟨hlo, hhi⟩, rfl⟩

/-! ## The Taylor constants

`bound_step` hard-codes the divisors 24 and 1920 and drops the odd terms.
These come from integrating the centered Taylor expansion of f about
c = (a+b)/2 over [a, b]:

  ∫ (x-c)   dx = 0,          ∫ (x-c)^2 dx = (b-a)^3/12,
  ∫ (x-c)^3 dx = 0,          ∫ (x-c)^4 dx = (b-a)^5/80.

With the Taylor factors 1/2! and 1/4! these are exactly the engine's
h^3/24 and h^5/1920 remainder/midpoint terms. -/

open intervalIntegral in
/-- Centered power integral reduced to a symmetric integral of `u^n`. -/
private lemma centered_pow_integral (a b : ℝ) (n : ℕ) :
    (∫ x in a..b, (x - (a + b) / 2) ^ n) =
      (((b - a) / 2) ^ (n + 1) - (-((b - a) / 2)) ^ (n + 1)) / (n + 1) := by
  have h := intervalIntegral.integral_comp_sub_right (a := a) (b := b)
    (fun u : ℝ => u ^ n) ((a + b) / 2)
  rw [h, integral_pow]
  have h1 : a - (a + b) / 2 = -((b - a) / 2) := by ring
  have h2 : b - (a + b) / 2 = (b - a) / 2 := by ring
  rw [h1, h2]

/-- Odd term 1 vanishes: `∫ x in a..b, (x − (a+b)/2) = 0`. -/
theorem integral_centered_one (a b : ℝ) :
    (∫ x in a..b, (x - (a + b) / 2)) = 0 := by
  have h := centered_pow_integral a b 1
  simpa using h.trans (by push_cast; ring)

/-- Even term 2: `∫ x in a..b, (x − (a+b)/2)^2 = (b−a)^3/12`.
With the Taylor factor 1/2! this is the engine's `h^3/24` term. -/
theorem integral_centered_sq (a b : ℝ) :
    (∫ x in a..b, (x - (a + b) / 2) ^ 2) = (b - a) ^ 3 / 12 := by
  have h := centered_pow_integral a b 2
  rw [h]; push_cast; ring

/-- Odd term 3 vanishes: `∫ x in a..b, (x − (a+b)/2)^3 = 0`. -/
theorem integral_centered_cube (a b : ℝ) :
    (∫ x in a..b, (x - (a + b) / 2) ^ 3) = 0 := by
  have h := centered_pow_integral a b 3
  rw [h]; push_cast; ring

/-- Even term 4: `∫ x in a..b, (x − (a+b)/2)^4 = (b−a)^5/80`.
With the Taylor factor 1/4! this is the engine's `h^5/1920` term. -/
theorem integral_centered_quartic (a b : ℝ) :
    (∫ x in a..b, (x - (a + b) / 2) ^ 4) = (b - a) ^ 5 / 80 := by
  have h := centered_pow_integral a b 4
  rw [h]; push_cast; ring

/-- The engine's two Taylor divisors in one statement: dividing the centered
even integrals by 2! and 4! yields exactly `h^3/24` and `h^5/1920`. -/
theorem taylor_constants_check (a b : ℝ) :
    (∫ x in a..b, (x - (a + b) / 2) ^ 2) / 2 = (b - a) ^ 3 / 24 ∧
    (∫ x in a..b, (x - (a + b) / 2) ^ 4) / 24 = (b - a) ^ 5 / 1920 := by
  refine ⟨?_, ?_⟩
  · rw [integral_centered_sq]; ring
  · rw [integral_centered_quartic]; ring

end JackalIv
