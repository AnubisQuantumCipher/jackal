/-
JackalIv/CertCheckMain.lean — the `jackal_cert_check` executable.

Reads a certificate's canonical text from the file named in `argv[1]` (or from
stdin when no path is given), runs the PROVED `Cert.parseCert` (the canonical
codec) and then the PROVED `Cert.checkCert` (the mechanized computable checker),
and reports:

  * `ACCEPT` on stdout, exit 0, iff parse succeeds and `checkCert = true`;
  * `REJECT <reason>` on stderr, exit 1, on any parse error or `checkCert = false`.

The binary is compiled DIRECTLY from the proved `parseCert`/`checkCert`
definitions — no `@[implemented_by]`, no `native_decide`, no re-implementation —
so what the executable accepts is exactly what `Cert.certified_release` certifies.
-/
import JackalIv.CertCodec

open JackalIv.Cert

/-- Parse then check, entirely through the proved definitions. -/
def runCert (s : String) : Except String Unit :=
  match parseCert s with
  | .error e => .error e
  | .ok (hdr, nodes) =>
      if checkCert hdr nodes then .ok ()
      else .error "checkCert rejected the certificate"

def main (args : List String) : IO UInt32 := do
  let input ← match args with
    | path :: _ => IO.FS.readFile path
    | []        => do let stdin ← IO.getStdin; stdin.readToEnd
  match runCert input with
  | .ok () =>
      IO.println "ACCEPT"
      pure 0
  | .error e =>
      (← IO.getStderr).putStrLn ("REJECT " ++ e)
      pure 1
