/-
JackalIv/CertCheckMain.lean — the request-bound `jackal_cert_check` executable.

Release mode takes exactly

  `<cert-path> range-bound-cert <raw-expression> <canonical-lo> <canonical-hi>`

It runs the proved canonical certificate parser/checker and then the proved
`requestMatches` decision, which independently parses/lowers the raw expression
with the exact-ℚ Lean parser and binds both canonical limits to the header.
That decision also requires every certificate node to be in the Lean-owned
FORMAL release allowlist; checker-sound but policy-unreleased constructors are
refused.
Only that five-argument mode reports a release ACCEPT.

The legacy one-path (or stdin) mode remains useful for inspecting certificate
bytes, but its success line is deliberately
`DIAGNOSTIC CERT-ONLY ACCEPT (NOT RELEASE-BOUND)` and MUST NOT be treated as a
release verdict.

The binary is compiled DIRECTLY from the proved `parseCert`/`checkCert`
definitions — no `@[implemented_by]`, no `native_decide`, no re-implementation —
and release mode additionally runs the exact decision consumed by
`request_bound_certified_release`.
-/
import JackalIv.CertRequest

open JackalIv.Cert

/-- Parse then check, entirely through the proved definitions.  The structured
result is retained for the independent request bind. -/
def checkedCert (s : String) : Except String (Header × List Node) :=
  match parseCert s with
  | .error e => .error e
  | .ok cert@(hdr, nodes) =>
      if checkCert hdr nodes then .ok cert
      else .error "checkCert rejected the certificate"

/-- Cert-only diagnostic.  Never emits the release ACCEPT token. -/
def runCertDiagnostic (s : String) : Except String Unit :=
  (checkedCert s).map (fun _ => ())

/-- Parse/check the cert and bind it to the exact operation, raw expression,
and canonical rational limits supplied by the caller.  On success returns the
validated header so the caller can echo the AUTHORITATIVE `output_lo/output_hi`
back to downstream verifiers — closing the parser-differential class where an
independent Python re-parse would otherwise report an interval the checker did
not attest (2026-08-15, §487-parserdiff audit). -/
def runRequestBound (s command rawExpr rawLo rawHi : String) :
    Except String Header := do
  let (hdr, nodes) ← checkedCert s
  if requestMatches command rawExpr rawLo rawHi hdr nodes then .ok hdr
  else .error "requestMatches rejected operation/expression/limits/status/interval-order/release-fragment"

def reject (e : String) : IO UInt32 := do
  (← IO.getStderr).putStrLn ("REJECT " ++ e)
  pure 1

def main (args : List String) : IO UInt32 := do
  match args with
  | [path, command, rawExpr, rawLo, rawHi] =>
      let input ← IO.FS.readFile path
      match runRequestBound input command rawExpr rawLo rawHi with
      | .ok hdr =>
          let outLo : String := String.ofList (ratToStr hdr.output_lo)
          let outHi : String := String.ofList (ratToStr hdr.output_hi)
          IO.println
            ("ACCEPT request-bound theorem=request_bound_certified_release" ++
             " command=range-bound-cert output " ++ outLo ++ " " ++ outHi)
          pure 0
      | .error e => reject e
  | [path] =>
      let input ← IO.FS.readFile path
      match runCertDiagnostic input with
      | .ok () =>
          IO.println "DIAGNOSTIC CERT-ONLY ACCEPT (NOT RELEASE-BOUND)"
          pure 0
      | .error e => reject e
  | [] =>
      let stdin ← IO.getStdin
      let input ← stdin.readToEnd
      match runCertDiagnostic input with
      | .ok () =>
          IO.println "DIAGNOSTIC CERT-ONLY ACCEPT (NOT RELEASE-BOUND)"
          pure 0
      | .error e => reject e
  | _ => reject "usage: jackal_cert_check <cert> range-bound-cert <expr> <canonical-lo> <canonical-hi>"
