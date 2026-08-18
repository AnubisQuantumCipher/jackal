/- Public composed-integral theorem signature contract. -/
import JackalIv.IntCertSound

namespace JackalIv.IntCert

open JackalIv MeasureTheory Set

/-- The artifact-core theorem closes every embedded model obligation without
an external `TreeTCB`. -/
theorem coreIntCert_hasNoExternalTreeTCB
    (hdr : IntHeader) (tree : List TreeNode) (q : QExpr)
    (hchk : checkIntCert hdr tree = .ok ())
    (hq : rootQExpr tree = some q) :
    IntervalIntegrable (sem (embedQ q)) volume ↑hdr.req_lo ↑hdr.req_hi ∧
    ((↑hdr.out_lo : ℝ) ≤
      ∫ x in (↑hdr.req_lo : ℝ)..↑hdr.req_hi, sem (embedQ q) x) ∧
    ((∫ x in (↑hdr.req_lo : ℝ)..↑hdr.req_hi, sem (embedQ q) x)
      ≤ (↑hdr.out_hi : ℝ)) :=
  int_cert_core_sound hdr tree q hchk hq

/-- The public theorem consumes only the executable request-bound checker
acceptance and returns the exact parsed/lowered caller-expression bind plus
the integral enclosure. -/
theorem publicIntCert_isRawRequestBound
    (rawExpr rawLo rawHi rawTol : String)
    (hdr : IntHeader) (tree : List TreeNode)
    (hchk : checkIntCertRequest rawExpr rawLo rawHi rawTol hdr tree = .ok ()) :
    ∃ ast lowered : Parser.RawExpr, ∃ q : QExpr,
      Parser.parseRaw rawExpr = some ast ∧
      Cert.lowerRaw ast = some lowered ∧
      rootRawExpr tree = some lowered ∧
      rootQExpr tree = some q ∧
      lowered.toExpr = embedQ q ∧
      Cert.parseRatCanon rawLo.toList = some hdr.req_lo ∧
      Cert.parseRatCanon rawHi.toList = some hdr.req_hi ∧
      Cert.parseRatCanon rawTol.toList = some hdr.tol ∧
      IntervalIntegrable (sem lowered.toExpr) volume ↑hdr.req_lo ↑hdr.req_hi ∧
      ((↑hdr.out_lo : ℝ) ≤
        ∫ x in (↑hdr.req_lo : ℝ)..↑hdr.req_hi, sem lowered.toExpr x) ∧
      ((∫ x in (↑hdr.req_lo : ℝ)..↑hdr.req_hi, sem lowered.toExpr x)
        ≤ (↑hdr.out_hi : ℝ)) :=
  int_cert_sound rawExpr rawLo rawHi rawTol hdr tree hchk

end JackalIv.IntCert
