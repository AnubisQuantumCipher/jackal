import JackalIv.Spacecraft.CertCodec

namespace JackalIv.Spacecraft

def minimalBytes : String :=
  "jackal-spacecraft-burn-cert v2\n" ++
  "config 80 1 32 1 1 1 1 1 1 1 0 1 1 1\n" ++
  "branch 0 0 1 2 3 4 5 6 7 8 9 10 11\n" ++
  "tube 0 0 20 21 22 23 24 25 26 27 28 29\n" ++
  "end 1 1 1\n"

def duplicateTerminalBytes : String := minimalBytes ++ "end 1 1 1\n"
def noncanonicalIntegerBytes : String := minimalBytes.replace "config 80" "config +80"
def trailingBytes : String := minimalBytes ++ "x\n"
def crlfBytes : String := minimalBytes.replace "\n" "\r\n"

def parsesB (s : String) : Bool := (parseBurnWitness s).isOk

#guard parsesB minimalBytes
#guard !(parsesB duplicateTerminalBytes)
#guard !(parsesB noncanonicalIntegerBytes)
#guard !(parsesB trailingBytes)
#guard !(parsesB crlfBytes)

end JackalIv.Spacecraft
