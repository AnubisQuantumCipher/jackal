/-
JackalIv/ShadowCertFixtures.lean — SHADOW (research-shadow, NON-AUTHORITATIVE).

In-kernel acceptance/refusal twins for the composition checker: tiny concrete
artifacts whose verdicts reduce under `decide`, pinning the checker's
behavior in the kernel itself (mirror of `CertCheck.lean`'s sanity block).

The fixtures use the integrand `x` (a single `var` certificate node, whose
out-interval is EXACTLY the input interval — no pads — so kernel reduction
is cheap) over `[0, 1]` with tolerance `2`, degree `0`, one range leaf.

No `sorry`, no axiom, no `native_decide`, no `@[implemented_by]`.
-/
import JackalIv.ShadowCertCheck

namespace JackalIv.Shadow

open JackalIv

/-- Embedded evaluation certificate for `x` over `[0, 1]`. -/
def fixCert : EvalCert :=
  { hdr := { schema_version := 2
             model_const_version := Cert.pinnedModelConst
             expr_commitment := "(var x)"
             source_commitment := ""
             input_lo := 0
             input_hi := 1
             root_id := 0
             output_lo := 0
             output_hi := 1
             exe_identity := ""
             status_class := "research-shadow" }
    nodes := [{ id := 0, op := "var", children := [], out_lo := 0,
                out_hi := 1, name := "x" }] }

/-- One accepted range leaf: claim `[0, 1] = (b−a)·[F.lo, F.hi]` exactly. -/
def fixLeaf : TreeNode :=
  { id := 0, kind := "range", a := 0, b := 1, lo := 0, hi := 1,
    children := [], certs := [fixCert] }

/-- The valid artifact header (released interval = root claim; width 1 ≤ 2). -/
def fixHeader : IntHeader :=
  { schema_version := 1
    model_const_version := Cert.pinnedModelConst
    checker_identity := shadowCheckerPin
    producer_identity := ""
    status_class := shadowStatus
    expr_commitment := "(var x)"
    source_commitment := ""
    req_lo := 0
    req_hi := 1
    tol := 2
    degree := 0
    root_id := 0
    out_lo := 0
    out_hi := 1 }

/-- Bool-level verdict probes.

NOTE (disclosed toolchain friction): concrete ℚ arithmetic does NOT reduce
under kernel `decide` at this Mathlib revision (the Field ℚ instance tower
blocks whnf; even `(1:ℚ) + 2 ≤ 4` fails `decide`), so these twins are
BUILD-TIME `#guard` probes evaluated by the compiler/interpreter — the same
evaluation lane as the shadow driver executable — rather than kernel
theorems.  The checker's SOUNDNESS is the kernel theorem `int_cert_sound`
(axioms: propext/Classical.choice/Quot.sound); these probes only pin the
concrete accept/refuse behavior against regressions in `lake build`. -/
def acceptsB (hdr : IntHeader) (tree : List TreeNode) : Bool :=
  match checkIntCert hdr tree with
  | .ok () => true
  | .error _ => false

/-- The exact refusal-reason probe. -/
def refusesWithB (hdr : IntHeader) (tree : List TreeNode) (reason : String) :
    Bool :=
  match checkIntCert hdr tree with
  | .ok () => false
  | .error e => e == reason

-- SANITY: the valid one-leaf artifact is accepted.
#guard acceptsB fixHeader [fixLeaf]

-- POISON TWIN (forged enclosure): the leaf claim narrowed below the range
-- ideal refuses with exactly the forged-enclosure reason.
#guard refusesWithB { fixHeader with out_lo := 1/4, out_hi := 3/4 }
      [{ fixLeaf with lo := 1/4, hi := 3/4 }]
      "forged-enclosure:lower" 

-- POISON TWIN (stale identity): a wrong checker pin refuses before any
-- semantic work.
#guard refusesWithB
      { fixHeader with checker_identity := "jackal-iv-bound-step-shadow-v0" }
      [fixLeaf] "stale-identity:checker" 

-- POISON TWIN (tolerance): a released interval wider than the tolerance
-- refuses with exactly the tolerance-unmet reason.
#guard refusesWithB { fixHeader with out_lo := -2, out_hi := 2 }
      [fixLeaf] "tolerance-unmet" 

-- POISON TWIN (reversed domain): a reversed request refuses as an invalid
-- interval before any tree work.
#guard refusesWithB { fixHeader with req_lo := 1, req_hi := 0 }
      [fixLeaf] "invalid-interval:request" 


end JackalIv.Shadow
