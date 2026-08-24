import JackalIv.Spacecraft.VectorField

namespace JackalIv.Spacecraft

#guard modelMatches pinnedModelRequest
#guard !modelMatches { pinnedModelRequest with thrustKmScale := 1 }
#guard pinnedModelRequest.dimension == 5
#guard pinnedModelRequest.mu == 1993002209 / 5000
#guard pinnedModelRequest.g0 == 196133 / 20000
#guard pinnedModelRequest.isp == 450
#guard pinnedModelRequest.thrustKmScale == 1 / 1000

noncomputable def unitState : State := ![6679, 0, 0, 7726 / 1000, 1200]

example (state : State) : (burnField 2000 state) 4 =
    -(2000 : ℝ) / ((450 : ℝ) * (196133 / 20000 : ℝ)) := by
  have h40 : (4 : Fin 5) ≠ 0 := by decide
  have h41 : (4 : Fin 5) ≠ 1 := by decide
  have h42 : (4 : Fin 5) ≠ 2 := by decide
  have h43 : (4 : Fin 5) ≠ 3 := by decide
  simp only [burnField, h40, h41, h42, h43, if_false]
  norm_num [pinnedModelRequest]

#guard domainAccepts 2
  ![⟨4, 8⟩, ⟨0, 1⟩, ⟨-1, 1⟩, ⟨4, 8⟩, ⟨4, 8⟩]
#guard !domainAccepts 2
  ![⟨0, 0⟩, ⟨0, 0⟩, ⟨-1, 1⟩, ⟨4, 8⟩, ⟨4, 8⟩]
#guard !domainAccepts 2
  ![⟨4, 8⟩, ⟨0, 1⟩, ⟨0, 0⟩, ⟨0, 0⟩, ⟨4, 8⟩]
#guard !domainAccepts 2
  ![⟨4, 8⟩, ⟨0, 1⟩, ⟨-1, 1⟩, ⟨4, 8⟩, ⟨0, 1⟩]

example {bits : Nat} {box : Box} {thrustIv : DInterval} {out : Box}
    (h : burnFieldIv bits box thrustIv = .ok out) :
    FieldDomain bits box ∧ out = burnFieldIvCore bits box thrustIv :=
  burnFieldIv_ok_iff.mp h

example {bits : Nat} {box : Box} {thrustIv : DInterval}
    {thrust : ℝ} {state : State}
    (hd : FieldDomain bits box)
    (hs : ∀ i, Mem bits (state i) (box i))
    (ht : Mem bits thrust thrustIv) :
    ∀ i, Mem bits ((burnField thrust state) i)
      ((burnFieldIvCore bits box thrustIv) i) :=
  fieldEnclosed hd hs ht

#print axioms fieldEnclosed
#print axioms burnField_contDiffOn_of_domain
#print axioms burnField_locallyLipschitzOn_of_domain

end JackalIv.Spacecraft
