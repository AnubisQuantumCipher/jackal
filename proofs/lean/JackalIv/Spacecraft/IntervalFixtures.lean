import JackalIv.Spacecraft.Interval

namespace JackalIv.Spacecraft

def i (lo hi : Int) : DInterval := ⟨lo, hi⟩

#guard add (i (-3) 4) (i 5 8) == i 2 12
#guard neg (i (-3) 4) == i (-4) 3
#guard sub (i (-3) 4) (i 5 8) == i (-11) (-1)
#guard mul 2 (i (-3) 4) (i 5 8) == i (-6) 8
#guard div 2 (i (-3) 4) (i 5 8) == .ok (i (-3) 4)
#guard match div 2 (i (-3) 4) (i (-1) 8) with
  | .error _ => true
  | .ok _ => false
#guard square 2 (i (-3) 4) == i 0 4
#guard sqrt 2 (i 4 9) == .ok (i 4 6)
#guard match sqrt 2 (i (-1) 9) with
  | .error _ => true
  | .ok _ => false
#guard hull (i (-3) 4) (i 5 8) == i (-3) 8
#guard intersection (i (-3) 6) (i 5 8) == some (i 5 6)
#guard intersection (i (-3) 4) (i 5 8) == none

example : Mem 2 (9 / 8 : ℝ) (mul 2 (i (-3) 4) (i 5 8)) := by
  have h := mul_sound (bits := 2) (a := i (-3) 4) (b := i 5 8)
    (x := (3 / 4 : ℝ)) (y := (3 / 2 : ℝ))
    (by norm_num [Mem, lower, upper, scale, i])
    (by norm_num [Mem, lower, upper, scale, i])
  norm_num at h ⊢
  exact h

example : ¬ Mem 2 (9 / 4 : ℝ) (i 0 8) := by
  norm_num [Mem, lower, upper, scale, i]

example : Mem 2 ((3 / 4 : ℝ) / (3 / 2 : ℝ))
    (divUnchecked 2 (i (-3) 4) (i 5 8)) := by
  apply div_sound
  · norm_num [Mem, lower, upper, scale, i]
  · norm_num [Mem, lower, upper, scale, i]
  · left
    norm_num [lower, scale, i]

example : Mem 2 (Real.sqrt 2)
    ⟨Int.sqrt (4 * scale 2), ceilSqrtInt (9 * scale 2)⟩ := by
  exact sqrt_sound (bits := 2) (a := i 4 9) (x := (2 : ℝ))
    (by norm_num [i]) (by norm_num)
    (by norm_num [Mem, lower, upper, scale, i])

#print axioms add_sound
#print axioms mul_sound
#print axioms div_sound
#print axioms square_sound
#print axioms sqrt_sound
#print axioms hull_sound_left
#print axioms hull_sound_right
#print axioms intersection_sound

end JackalIv.Spacecraft
