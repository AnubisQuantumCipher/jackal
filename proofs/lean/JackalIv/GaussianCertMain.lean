/-
JackalIv/GaussianCertMain.lean — independent executable checker for
`jackal-gaussian-integral-cert v1`.

The binary invokes the same `parseCert` and `checkCert` definitions appearing
in `gaussian_integral_check_sound`; there is no alternate native checker.
-/
import JackalIv.GaussianCert

open JackalIv.GaussianCert


def runGaussianCert (input : String) : Except String Unit :=
  match parseCert input with
  | .error error => .error error
  | .ok cert =>
      if checkCert cert then .ok ()
      else .error "checkCert rejected the gaussian certificate"


def main (args : List String) : IO UInt32 := do
  let input ← match args with
    | path :: _ => IO.FS.readFile path
    | [] => do
        let stdin ← IO.getStdin
        stdin.readToEnd
  match runGaussianCert input with
  | .ok () =>
      IO.println "ACCEPT theorem=gaussian_integral_check_sound family=gaussian-exp-square-v1"
      pure 0
  | .error error =>
      (← IO.getStderr).putStrLn ("REJECT " ++ error)
      pure 1
