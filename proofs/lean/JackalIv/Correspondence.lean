/-
JackalIv/Correspondence.lean — the mission's TOP theorem: the parser/lowering
front end of the engine composed with the interval composition theorem, so a
completed run of the certified `ieval` encloses the exact real semantics of the
SOURCE expression the user typed.

## Hypothesis ↔ engine-pipeline map (the engine is the authority)

| Lean hypothesis                | engine artifact (`jackal_calc.anb`)                       |
|--------------------------------|-----------------------------------------------------------|
| `parse s = some ast`           | `tokenize` + `ast_parse_expr` … `ast_parse_atom`          |
| `lower ast = some e`           | `simplify_bound` (bottom-up algebraic-identity rewrite)   |
| `Runs e (a,b) (lo,hi)`         | a completed `ieval` run on `[a,b]` producing `[lo,hi]`    |
| `sem ast` / `sem e`            | the exact real-number denotation of the AST               |
| `DefinedOn ast x`              | pointwise shadow of `ieval`'s `iv_bad` refusal guards     |

The chain is: the PARSER (`Parser.parse`) DEFINES the denotation `sem ast` of the
admitted source string, and LOWERING (`lower`) PRESERVES it
(`Lower.lower_preserves_sem`) — so the value the interval engine actually bounds
(`sem e`) is exactly the value the user's expression denotes (`sem ast`).
Composing that identity with the interval composition theorem
(`Embed.runs_encloses`, itself the per-operator Arith/Monotone/Exact/Pow lemmas
threaded through the whole tree) yields `parse_lower_encloses`: over a nonempty
input interval, every completed `ieval` run encloses the exact source semantics
at every point.

## What is and is NOT established here

* PROVED here: `parse_lower_denotes` (the admitted source denotes `sem ast`, and
  lowering preserves that denotation onto the bounded `e`) and
  `parse_lower_encloses` (the enclosure bridge to the composition theorem).
* NOT proved here, enforced elsewhere or deferred (honest residuals):
  - The parser's byte-for-byte identity to the SHIPPED engine parser over the
    full input space is a DIFFERENTIAL GATE (`tests/parser_differential.py`),
    not a theorem — `Parser.lean` proves determinism, rejection, and corpus
    reproduction (the in-kernel mirror), never full-space engine identity.
  - `ieval → Runs` (that an actual `ieval` execution induces a `Runs`
    derivation) and source → native refinement (verified compilation of the
    Anubis lane) remain DEFERRED — see the Ledger's "Next mechanization wave"
    items (3) and (5).  We do NOT claim them.

## S-expr dump entry points (for the differential gate's executable)

`parseSexp` re-exports `Parser.parseDumpString` (parse → engine parse s-expr,
corpus column 2).  `lowerSexp` parses, lowers, and serializes the LOWERED tree
(corpus column 3), refusing (`none`) exactly when parsing or lowering refuses.
-/
import JackalIv.Parser
import JackalIv.Lower
import JackalIv.Dump
import JackalIv.Embed

namespace JackalIv

open Parser (parse parseDumpString exprToSexp)

/-! ### The mission's top theorem: parse defines, lowering preserves -/

/-- TOP THEOREM (denotation).  The parser DEFINES the denotation `sem ast` of the
admitted source string `s`, and lowering PRESERVES it: whenever `s` parses to
`ast` and `ast` lowers to the bounded expression `e`, the two agree on the
defined domain of the source.  Immediate from `Lower.lower_preserves_sem`; the
`parse` hypothesis records that `ast` (hence `sem ast`) is exactly what the
engine's front end admitted. -/
theorem parse_lower_denotes {s : String} {ast e : Expr}
    (hparse : parse s = some ast) (hlower : lower ast = some e) :
    ∀ x, DefinedOn ast x → sem e x = sem ast x := by
  intro x hx
  exact lower_preserves_sem ast x hx e hlower

/-! ### Enclosure bridge to the interval composition theorem -/

/-- ENCLOSURE BRIDGE.  Composing `parse_lower_denotes` with the interval
composition theorem `Embed.runs_encloses`: if the source `s` parses to `ast`,
lowers to `e`, and a completed `ieval` run on the nonempty interval `[a, b]`
produced the box `[lo, hi]`, then at EVERY point `x ∈ [a, b]` where the SOURCE is
defined, the exact source value `sem ast x` lies in `[lo, hi]`.

The engine bounds `sem e`; `parse_lower_denotes` identifies `sem e x` with the
source value `sem ast x` on the defined domain (definedness of `ast` transfers to
`e` via `Lower.lower_preserves_defined`, which `runs_encloses` re-derives
internally), so the enclosure lands on the value the user's expression
denotes. -/
theorem parse_lower_encloses {s : String} {ast e : Expr} {a b lo hi : ℝ}
    (hparse : parse s = some ast) (hlower : lower ast = some e)
    (hrun : Runs e (a, b) (lo, hi)) (hab : a ≤ b) :
    ∀ x ∈ Set.Icc a b, DefinedOn ast x → sem ast x ∈ Set.Icc lo hi := by
  intro x hx hdef
  have hsem : sem e x = sem ast x := parse_lower_denotes hparse hlower x hdef
  have henc : sem e x ∈ Set.Icc lo hi := (runs_encloses hrun hab x hx).2
  rw [← hsem]
  exact henc

/-! ### S-expr dump entry points (the differential gate's executable calls these) -/

/-- Re-export: parse a source string to the engine's parse s-expr (corpus
column 2), reproducing `ast_sexp` on the UNLOWERED tree.  The verified body is
noncomputable (it constructs `Expr.num (strToReal t) t` over `ℝ`); the
`@[implemented_by]` supplies the runnable, real-free mirror `Dump.parseSexpImpl`
for the differential-gate executable (a trusted mirror, part of that gate's TCB;
see `Dump.lean` and the Ledger — it adds no axiom and changes no theorem). -/
@[implemented_by Dump.parseSexpImpl]
noncomputable def parseSexp : String → Option String := parseDumpString

/-- Parse, lower, and serialize the LOWERED tree to the engine's lowered s-expr
(corpus column 3); `none` exactly when parsing or lowering refuses.  Runnable via
the `@[implemented_by]` mirror `Dump.lowerSexpImpl` (same trust note as above). -/
@[implemented_by Dump.lowerSexpImpl]
noncomputable def lowerSexp : String → Option String :=
  fun s => (parse s).bind (fun ast => (lower ast).map exprToSexp)

#print axioms parse_lower_denotes
#print axioms parse_lower_encloses

end JackalIv
