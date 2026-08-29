/- Public fail-closed CLI for the machine-checked finite-burn certificate. -/
import JackalIv.Spacecraft.CertSound

open JackalIv.Spacecraft

def main (args : List String) : IO UInt32 := do
  match args with
  | [path, requestDigest, modelId, epoch] =>
      try
        let metadata ← (System.FilePath.mk path).metadata
        if metadata.type != .file then
          IO.eprintln "REJECT unreadable-witness"
          pure 1
        else if maxWitnessBytes.toUInt64 < metadata.byteSize then
          IO.eprintln "REJECT witness-too-large"
          pure 1
        else
          let raw ← IO.FS.readFile path
          match checkBurnCert raw requestDigest modelId epoch with
          | .ok accepted =>
              IO.println ("ACCEPT theorem=spacecraft_burn_certified_safe " ++
                s!"status=formal-bounded margin_lo={accepted.margin.lo} " ++
                s!"margin_hi={accepted.margin.hi} model={modelId} epoch={epoch}")
              pure 0
          | .error reason =>
              IO.eprintln s!"REJECT {reason}"
              pure 1
      catch _ =>
        IO.eprintln "REJECT unreadable-witness"
        pure 1
  | _ =>
      IO.eprintln "REJECT usage"
      pure 2
