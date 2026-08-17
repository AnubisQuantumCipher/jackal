/-
JackalIv/ShadowCertMain.lean — SHADOW (research-shadow, NON-AUTHORITATIVE).

Driver for the v1.7 `bound_step` composition checker.  NOT a lakefile
executable target and NOT part of the 33-tool public inventory: it runs only
through `lake env lean --run JackalIv/ShadowCertMain.lean <artifact>` — a
deliberately non-public invocation path (mission §7).

Accept (exit 0, stdout):
  SHADOW-ACCEPT status=research-shadow theorem=int_cert_sound
    checker=jackal-iv-bound-step-shadow-v1 output <lo> <hi>

Refuse (exit 1, stderr):
  SHADOW-REFUSE reason=<class>[:<detail>]

The verdict is computed by the PROVED `parseIntCert` + `checkIntCert`
(no `native_decide`, no `@[implemented_by]` anywhere on the path); the
enclosure meaning of an accept is exactly `int_cert_sound` under `TreeTCB`.
An accept is NEVER a release: the status class is pinned `research-shadow`
and no public tool can reach this driver.
-/
import JackalIv.ShadowCertCodec
import JackalIv.ShadowCertCheck
import JackalIv.ShadowCertSound

open JackalIv.Shadow

def main (args : List String) : IO UInt32 := do
  match args with
  | [path] => do
      let text ← IO.FS.readFile path
      match parseIntCert text with
      | .error e =>
          IO.eprintln s!"SHADOW-REFUSE reason={e}"
          return 1
      | .ok (hdr, tree) =>
          match checkIntCert hdr tree with
          | .error e =>
              IO.eprintln s!"SHADOW-REFUSE reason={e}"
              return 1
          | .ok () =>
              let lo := String.ofList (JackalIv.Cert.ratToStr hdr.out_lo)
              let hi := String.ofList (JackalIv.Cert.ratToStr hdr.out_hi)
              IO.println (s!"SHADOW-ACCEPT status=research-shadow " ++
                s!"theorem=int_cert_sound checker={shadowCheckerPin} " ++
                s!"output {lo} {hi}")
              return 0
  | _ => do
      IO.eprintln "usage: lake env lean --run JackalIv/ShadowCertMain.lean <artifact>"
      return 2
