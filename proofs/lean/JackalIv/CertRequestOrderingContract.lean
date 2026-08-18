/-
Fail-closed interval-ordering contract for the request-bound range checker.

This module is intentionally kept separate from `CertRequest.lean` so the
regression can be observed RED before the production matcher is changed.
-/
import JackalIv.CertRequest

namespace JackalIv.Cert

/-- A constant certificate whose input interval is reversed.  The node does
not depend on the interval, so the existing certificate-only checker accepts
it and exposes the missing request-bound ordering premise directly. -/
def reversedInputHeader : Header :=
  { schema_version := 2
    model_const_version := pinnedModelConst
    expr_commitment := "(num 0)"
    source_commitment := ""
    input_lo := 2, input_hi := 1
    root_id := 0
    output_lo := 0, output_hi := 0
    exe_identity := ""
    status_class := "bounded" }

def reversedInputNodes : List Node :=
  [{ id := 0, op := "num_exact", children := [], out_lo := 0, out_hi := 0,
     name := "0", value := 0 }]

theorem reversedInput_certOnlyChecks :
    checkCert reversedInputHeader reversedInputNodes = true := by
  decide

/-- Release request matching must reject a reversed input interval even when
the certificate-only checker accepts the same bytes. -/
theorem requestRejects_reversedInput :
    requestMatches "range-bound-cert" "0" "2" "1"
      reversedInputHeader reversedInputNodes = false := by
  decide

/-- The coherent exploit shape observed against the v1.7.0 direct checker:
both the variable and negation boxes are reversed, yet `checkCert` reduces to
true because ordering was an external theorem premise. -/
def coherentlyReversedNodes : List Node :=
  [ { id := 0, op := "var", children := [], out_lo := 5, out_hi := 2, name := "x" },
    { id := 1, op := "neg", children := [0], out_lo := -2, out_hi := -5 } ]

def coherentlyReversedHeader : Header :=
  { schema_version := 2
    model_const_version := pinnedModelConst
    expr_commitment := "(neg (var x))"
    source_commitment := ""
    input_lo := 5, input_hi := 2
    root_id := 1
    output_lo := -2, output_hi := -5
    exe_identity := ""
    status_class := "bounded" }

theorem coherentlyReversed_certOnlyChecks :
    checkCert coherentlyReversedHeader coherentlyReversedNodes = true := by
  decide

theorem requestRejects_coherentlyReversed :
    requestMatches "range-bound-cert" "-x" "5" "2"
      coherentlyReversedHeader coherentlyReversedNodes = false := by
  decide

/-- Output ordering is also a release-request invariant, independent of
whether a later semantic checker would reject this deliberately malformed
root box. -/
def reversedOutputHeader : Header :=
  { validHeader with output_lo := -2, output_hi := -5 }

def reversedOutputNodes : List Node :=
  [ { id := 0, op := "var", children := [], out_lo := 2, out_hi := 5, name := "x" },
    { id := 1, op := "neg", children := [0], out_lo := -2, out_hi := -5 } ]

theorem requestRejects_reversedOutput :
    requestMatches "range-bound-cert" "-x" "2" "5"
      reversedOutputHeader reversedOutputNodes = false := by
  decide

/-- The public release theorem must be callable using only the two executable
acceptance predicates.  Interval ordering and the vacuous model TCB for the
release allowlist must be derived from those predicates, not supplied by an
external caller. -/
theorem publicRelease_hasNoExternalPremises
    {command rawExpr rawLo rawHi : String} {hdr : Header} {nodes : List Node}
    (hreq : requestMatches command rawExpr rawLo rawHi hdr nodes = true)
    (hchk : checkCert hdr nodes = true) :
    ∃ ast : Expr, Parser.parse rawExpr = some ast ∧
      ∀ x ∈ Set.Icc (↑hdr.input_lo : ℝ) (↑hdr.input_hi),
        DefinedOn ast x → sem ast x ∈ Set.Icc (↑hdr.output_lo : ℝ) (↑hdr.output_hi) :=
  request_bound_certified_release hreq hchk

end JackalIv.Cert
