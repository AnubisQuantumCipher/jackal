/-
JackalIv/ParseDumpMain.lean — the command-line dumper used by the parser/lowering
DIFFERENTIAL GATE (`tests/parser_differential.py`).  It exposes the verified
front-end s-expr functions of the mission's top theorem so the gate can compare
their output, byte-for-byte, against the shipped engine's `ast_sexp`.

Contract (argv = `[mode, expr]`):

* `mode = "parse"` — print `JackalIv.parseSexp expr` (parse → engine parse
  s-expr, corpus column 2) and exit 0; on refusal (`none`) print nothing, exit 1.
* `mode = "lower"` — print `JackalIv.lowerSexp expr` (parse → lower → lowered
  s-expr, corpus column 3) and exit 0; on refusal (`none`) print nothing, exit 1.
* any other mode (or wrong argument count) — print nothing, exit 2.

`parseSexp` / `lowerSexp` are the noncomputable verified functions of
`Correspondence.lean`; they run here through the trusted `@[implemented_by]`
mirror in `Dump.lean` (see the Ledger's "Parser / lowering bridge" and residuals
for the exact trust boundary).
-/
import JackalIv.Correspondence

open JackalIv (parseSexp lowerSexp)

/-- Print the s-expr the given verified dump function produces, or exit 1 on a
refusal (`none`), printing nothing. -/
def emit (result : Option String) : IO UInt32 :=
  match result with
  | some s => do IO.println s; pure 0
  | none => pure 1

def main (args : List String) : IO UInt32 := do
  match args with
  | [mode, expr] =>
    match mode with
    | "parse" => emit (parseSexp expr)
    | "lower" => emit (lowerSexp expr)
    | _ => pure 2
  | _ => pure 2
