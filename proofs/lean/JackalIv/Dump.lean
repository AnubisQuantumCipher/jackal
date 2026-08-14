/-
JackalIv/Dump.lean — a COMPUTABLE mirror of the parse→(lower)→s-expr pipeline,
used ONLY to give the differential-gate executable (`ParseDumpMain`) a runnable
implementation of the (necessarily noncomputable) verified dump functions
`Correspondence.parseSexp` / `Correspondence.lowerSexp`.

## Why a mirror is needed

The verified parser (`Parser.parse`) builds `Syntax.Expr` nodes whose `num`
constructor carries a REAL value `Parser.strToReal t : ℝ`.  Real numbers have no
runtime representation, so `parse` — and hence `parseSexp` / `lowerSexp` — are
`noncomputable` and cannot be compiled into an executable.  This file rebuilds
the SAME control flow over a real-free tree `CExpr` (whose `num` carries only the
verbatim token text), reusing the verified, already-computable tokenizer
(`Parser.tokenize`), known-name tables, and exact-rational value
(`Parser.numTextToRat : String → ℚ`).

## Faithfulness

Every function here is a constructor-for-constructor transcription of its
`Parser` / `Lower` counterpart:

* `cparse*` mirrors `Parser.parseExpr … parseAtom` (same fuel `3·|ts|+10`, same
  left/right associativity, same known-function/arity/constant checks).
* `csexp` mirrors `Parser.exprToSexp` byte-for-byte (token text for `num`,
  `const` head for `constant`, unified `call` head).
* `clower` mirrors `Lower.lower`; the engine's "is `(num v)`" tests inspect the
  num's REAL value, and `Parser.numTextToRat t = 0` (resp. `= 1`) in `ℚ` iff
  `strToReal t = 0` (resp. `= 1`) in `ℝ` (the `ℚ ↪ ℝ` cast is injective), so the
  rational probe `cnumVal?` decides exactly the same rewrites.

The mirror is wired to the verified functions by a trusted `@[implemented_by]`
in `Correspondence.lean`: the compiled executable dispatches
`JackalIv.parseSexp` / `JackalIv.lowerSexp` to `parseSexpImpl` / `lowerSexpImpl`
here.  This attribute is part of the executable's TCB (the parse↔engine
correspondence is a DIFFERENTIAL GATE, not a proof — see the Ledger); it adds no
axiom to and changes no logical content of any theorem, and the in-kernel corpus
lemmas of `Parser.lean` independently pin the noncomputable spec to the corpus.
-/
import JackalIv.Parser

namespace JackalIv
namespace Dump

open Parser (Token tokenize numTextToRat isUnaryFn isBinaryFn isConstName)

/-! ### Real-free mirror AST -/

/-- A structural copy of `Syntax.Expr` whose `num` node carries ONLY the
verbatim token text (no real value), so the whole pipeline stays computable. -/
inductive CExpr
  | num (t : String)
  | var (name : String)
  | constant (name : String)
  | neg (u : CExpr)
  | add (l r : CExpr)
  | sub (l r : CExpr)
  | mul (l r : CExpr)
  | div (l r : CExpr)
  | mod (l r : CExpr)
  | pow (base exponent : CExpr)
  | call1 (name : String) (u : CExpr)
  | call2 (name : String) (u v : CExpr)
  deriving Inhabited

/-! ### Engine s-expr serializer (mirror of `Parser.exprToSexp`) -/

/-- Byte-for-byte copy of `Parser.exprToSexp` on the real-free tree. -/
def csexp : CExpr → String
  | .num t => "(num " ++ t ++ ")"
  | .var n => "(var " ++ n ++ ")"
  | .constant n => "(const " ++ n ++ ")"
  | .neg u => "(neg " ++ csexp u ++ ")"
  | .add l r => "(add " ++ csexp l ++ " " ++ csexp r ++ ")"
  | .sub l r => "(sub " ++ csexp l ++ " " ++ csexp r ++ ")"
  | .mul l r => "(mul " ++ csexp l ++ " " ++ csexp r ++ ")"
  | .div l r => "(div " ++ csexp l ++ " " ++ csexp r ++ ")"
  | .mod l r => "(mod " ++ csexp l ++ " " ++ csexp r ++ ")"
  | .pow b e => "(pow " ++ csexp b ++ " " ++ csexp e ++ ")"
  | .call1 name u => "(call " ++ name ++ " " ++ csexp u ++ ")"
  | .call2 name u v => "(call " ++ name ++ " " ++ csexp u ++ " " ++ csexp v ++ ")"

/-! ### Recursive-descent parser (fuel-structural mirror of `Parser.parse*`) -/

mutual
  /-- `expr := term (('+'|'-') term)*` -/
  def cparseExpr (fuel : Nat) (ts : List Token) : Option (CExpr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match cparseTerm f ts with
      | none => none
      | some (e, rest) => cparseExprTail f e rest

  /-- Left-associative `('+'|'-') term` tail loop. -/
  def cparseExprTail (fuel : Nat) (acc : CExpr) (ts : List Token) :
      Option (CExpr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match ts with
      | Token.tplus :: rest =>
        match cparseTerm f rest with
        | none => none
        | some (e2, rest2) => cparseExprTail f (CExpr.add acc e2) rest2
      | Token.tminus :: rest =>
        match cparseTerm f rest with
        | none => none
        | some (e2, rest2) => cparseExprTail f (CExpr.sub acc e2) rest2
      | _ => some (acc, ts)

  /-- `term := unary (('*'|'/'|'%') unary)*` -/
  def cparseTerm (fuel : Nat) (ts : List Token) : Option (CExpr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match cparseUnary f ts with
      | none => none
      | some (e, rest) => cparseTermTail f e rest

  /-- Left-associative `('*'|'/'|'%') unary` tail loop. -/
  def cparseTermTail (fuel : Nat) (acc : CExpr) (ts : List Token) :
      Option (CExpr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match ts with
      | Token.tstar :: rest =>
        match cparseUnary f rest with
        | none => none
        | some (e2, rest2) => cparseTermTail f (CExpr.mul acc e2) rest2
      | Token.tslash :: rest =>
        match cparseUnary f rest with
        | none => none
        | some (e2, rest2) => cparseTermTail f (CExpr.div acc e2) rest2
      | Token.tpercent :: rest =>
        match cparseUnary f rest with
        | none => none
        | some (e2, rest2) => cparseTermTail f (CExpr.mod acc e2) rest2
      | _ => some (acc, ts)

  /-- `unary := '-' unary | power` -/
  def cparseUnary (fuel : Nat) (ts : List Token) : Option (CExpr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match ts with
      | Token.tminus :: rest =>
        match cparseUnary f rest with
        | none => none
        | some (e, rest2) => some (CExpr.neg e, rest2)
      | _ => cparsePower f ts

  /-- `power := atom ('^' unary)?` — one optional `^`, RHS `unary`. -/
  def cparsePower (fuel : Nat) (ts : List Token) : Option (CExpr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match cparseAtom f ts with
      | none => none
      | some (base, rest) =>
        match rest with
        | Token.tcaret :: rest2 =>
          match cparseUnary f rest2 with
          | none => none
          | some (ex, rest3) => some (CExpr.pow base ex, rest3)
        | _ => some (base, rest)

  /-- `atom := num | '(' expr ')' | ident '(' args ')' | ident`. -/
  def cparseAtom (fuel : Nat) (ts : List Token) : Option (CExpr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match ts with
      | Token.tnum t :: rest => some (CExpr.num t, rest)
      | Token.tlparen :: rest =>
        match cparseExpr f rest with
        | none => none
        | some (e, rest2) =>
          match rest2 with
          | Token.trparen :: rest3 => some (e, rest3)
          | _ => none
      | Token.tident name :: rest =>
        match rest with
        | Token.tlparen :: rest2 =>
          match cparseArgs f rest2 with
          | none => none
          | some (args, rest3) =>
            match rest3 with
            | Token.trparen :: rest4 =>
              if isUnaryFn name then
                match args with
                | [a] => some (CExpr.call1 name a, rest4)
                | _ => none
              else if isBinaryFn name then
                match args with
                | [a, b] => some (CExpr.call2 name a b, rest4)
                | _ => none
              else none
            | _ => none
        | _ =>
          if isConstName name then some (CExpr.constant name, rest)
          else some (CExpr.var name, rest)
      | _ => none

  /-- `args := (expr (',' expr)*)?` -/
  def cparseArgs (fuel : Nat) (ts : List Token) : Option (List CExpr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match ts with
      | Token.trparen :: _ => some ([], ts)
      | _ =>
        match cparseExpr f ts with
        | none => none
        | some (e, rest) => cparseArgsTail f [e] rest

  /-- `(',' expr)*` tail loop. -/
  def cparseArgsTail (fuel : Nat) (acc : List CExpr) (ts : List Token) :
      Option (List CExpr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match ts with
      | Token.tcomma :: rest =>
        match cparseExpr f rest with
        | none => none
        | some (e, rest2) => cparseArgsTail f (acc ++ [e]) rest2
      | _ => some (acc, ts)
end

/-- Parse a source string to `CExpr` (mirror of `Parser.parse`). -/
def cparse (s : String) : Option CExpr :=
  match tokenize s with
  | none => none
  | some ts =>
    match cparseExpr (3 * ts.length + 10) ts with
    | none => none
    | some (e, rest) =>
      match rest with
      | [Token.tend] => some e
      | _ => none

/-! ### Lowering (mirror of `Lower.lower`)

The engine's "is `(num v)`" tests inspect the num's REAL value; the rational
probe below decides them identically (`ℚ ↪ ℝ` injective). -/

/-- Exact rational value of a `num` node (mirror of `Lower.numVal?`, but the
computable rational rather than the noncomputable real). -/
def cnumVal? : CExpr → Option ℚ
  | .num t => some (numTextToRat t)
  | _ => none

/-- Single neg-neg collapse (mirror of `Lower.lowerNeg`). -/
def clowerNeg : CExpr → CExpr
  | .neg w => w
  | u => .neg u

def clowerAdd (l r : CExpr) : CExpr :=
  if cnumVal? l = some 0 then r
  else if cnumVal? r = some 0 then l
  else .add l r

def clowerSub (l r : CExpr) : CExpr :=
  if cnumVal? r = some 0 then l
  else if cnumVal? l = some 0 then clowerNeg r
  else .sub l r

def clowerMul (l r : CExpr) : CExpr :=
  if cnumVal? l = some 1 then r
  else if cnumVal? r = some 1 then l
  else .mul l r

def clowerDiv (l r : CExpr) : Option CExpr :=
  if cnumVal? r = some 0 then none
  else if cnumVal? r = some 1 then some l
  else some (.div l r)

def clowerMod (l r : CExpr) : Option CExpr :=
  if cnumVal? r = some 0 then none
  else some (.mod l r)

def clowerPow (b e : CExpr) : CExpr :=
  if cnumVal? e = some 1 then b
  else .pow b e

/-- Bottom-up algebraic-identity lowering (mirror of `Lower.lower`). -/
def clower : CExpr → Option CExpr
  | .num t => some (.num t)
  | .var n => some (.var n)
  | .constant n => some (.constant n)
  | .neg u =>
      match clower u with
      | some u' => some (clowerNeg u')
      | none => none
  | .add l r =>
      match clower l, clower r with
      | some l', some r' => some (clowerAdd l' r')
      | _, _ => none
  | .sub l r =>
      match clower l, clower r with
      | some l', some r' => some (clowerSub l' r')
      | _, _ => none
  | .mul l r =>
      match clower l, clower r with
      | some l', some r' => some (clowerMul l' r')
      | _, _ => none
  | .div l r =>
      match clower l, clower r with
      | some l', some r' => clowerDiv l' r'
      | _, _ => none
  | .mod l r =>
      match clower l, clower r with
      | some l', some r' => clowerMod l' r'
      | _, _ => none
  | .pow b e =>
      match clower b, clower e with
      | some b', some e' => some (clowerPow b' e')
      | _, _ => none
  | .call1 name u =>
      match clower u with
      | some u' => some (.call1 name u')
      | none => none
  | .call2 name u v =>
      match clower u, clower v with
      | some u', some v' => some (.call2 name u' v')
      | _, _ => none

/-! ### Dump entry points (the `@[implemented_by]` targets) -/

/-- Computable implementation of `Correspondence.parseSexp`: parse → engine
parse s-expr (corpus column 2). -/
def parseSexpImpl (s : String) : Option String := (cparse s).map csexp

/-- Computable implementation of `Correspondence.lowerSexp`: parse → lower →
lowered s-expr (corpus column 3); `none` exactly when parse or lower refuses. -/
def lowerSexpImpl (s : String) : Option String :=
  (cparse s).bind (fun ast => (clower ast).map csexp)

end Dump
end JackalIv
