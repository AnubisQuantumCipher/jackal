/-
JackalIv/IntCertMain.lean — public certified integrate-bound-cert lane (v1.7).

Driver for the `bound_step` composition checker, compiled as the lakefile
executable target `jackal_int_cert_check` (the fourth pinned checker
executable, alongside `jackal_cert_check` / `jackal_gaussian_check` /
`jackal_parse_dump`).

Accept (exit 0, stdout):
  ACCEPT status=bounded theorem=int_cert_sound
    checker=jackal-iv-bound-step-v1 output <lo> <hi>

Refuse (exit 1, stderr):
  REFUSE reason=<class>[:<detail>]

The verdict is computed by the PROVED `parseIntCert` +
`checkIntCertRequest`
(no `native_decide`, no `@[implemented_by]` anywhere on the path); the
enclosure meaning of an accept is exactly raw-request-bound `int_cert_sound`.
The artifact status class is pinned `bounded`: an accept never self-inflates —
`formal-bounded` is derived downstream by the fail-closed release validator
(request-commitment binding + TOCTOU executable identity), exactly like the
existing range/gaussian checker lanes.
-/
import JackalIv.IntCertCodec
import JackalIv.IntCertCheck
import JackalIv.IntCertSound

open JackalIv.IntCert

def main (args : List String) : IO UInt32 := do
  match args with
  | [path, rawExpr, rawLo, rawHi, rawTol] => do
      let text ← IO.FS.readFile path
      match parseIntCert text with
      | .error e =>
          IO.eprintln s!"REFUSE reason={e}"
          return 1
      | .ok (hdr, tree) =>
          match checkIntCertRequest rawExpr rawLo rawHi rawTol hdr tree with
          | .error e =>
              IO.eprintln s!"REFUSE reason={e}"
              return 1
          | .ok () =>
              let lo := String.ofList (JackalIv.Cert.ratToStr hdr.out_lo)
              let hi := String.ofList (JackalIv.Cert.ratToStr hdr.out_hi)
              IO.println (s!"ACCEPT status=bounded " ++
                s!"theorem=int_cert_sound checker={intCertCheckerPin} " ++
                s!"output {lo} {hi}")
              return 0
  | _ => do
      IO.eprintln
        "usage: jackal_int_cert_check <artifact> <raw-expression> <lo> <hi> <tolerance>"
      return 2
