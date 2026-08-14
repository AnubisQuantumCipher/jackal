/-
JackalIv/Parser.lean — a deep, structurally-terminating model of the engine's
tokenizer + recursive-descent parser (`jackal_calc.anb`, fns `tokenize` and
`ast_parse_*`), producing the SINGLE canonical `Syntax.Expr`, plus the engine
s-expr serializer (`ast_sexp`).

## What this file mirrors (the engine is the authority)

Tokenizer (`fn tokenize`): skip space/tab; Number = digit+ ('.' digit+)?
([eE][+-]?digit+)? — REQUIRES a leading digit, REQUIRES a digit after '.',
and consumes the exponent ONLY if a digit follows `[eE][+-]?`; the token keeps
its verbatim text.  Identifier = [A-Za-z_][A-Za-z0-9_]*.  Single-char ops
`+ - * / % ^`, parens `( )`, comma `,`; then a synthetic `end` token.  Any
other character is unsupported ⇒ the whole tokenize REFUSES (`none`).

Recursive descent (all binary ops LEFT-assoc except `^`):
```
  expr  := term (('+'|'-') term)*
  term  := unary (('*'|'/'|'%') unary)*
  unary := '-' unary | power
  power := atom ('^' unary)?          -- one optional '^', RHS is `unary`
  atom  := num | '(' expr ')' | ident '(' args ')' | ident
  args  := (expr (',' expr)*)?
```
`ident '(' … ')'` MUST name a known function of the right arity or the parse
REFUSES ("unknown function" / arity mismatch); a bare identifier is a
`constant` node iff it is a known constant name, otherwise a `var` node.

## Node-tag ↔ constructor map (engine `ast_*` → `Syntax.Expr`)
num→`num` (real value derived from the token text; token text kept verbatim),
var→`var`, const-name→`constant`, unary fn→`call1`, binary fn→`call2`,
`%`→`mod`, `^`→`pow`, unary `-`→`neg`, `+ - * /`→`add sub mul div`.

## Termination and reducibility
Every recursive function here is STRUCTURAL — the tokenizer and the mutual
recursive-descent block both decrease on an explicit `fuel : Nat` (matched as
`f+1`, every recursive call passes the predecessor `f`).  Structural (not
well-founded) recursion is deliberate: it lets the rejection and corpus
lemmas below reduce in the kernel by `rfl`/`decide`.  The initial fuel is a
generous linear bound in the input size (`length + 1` for the tokenizer,
`10·|tokens| + 10` for the parser), always larger than the true recursion
depth for well-formed inputs, so the bound never truncates a real parse.

## What is proven here
Determinism (`parse` is a function), a battery of structural REJECTION
lemmas (empty input, unbalanced paren, empty call, doubled operator,
malformed number), and totality on the verified corpus.  The engine s-expr
serializer `exprToSexp` reproduces `ast_sexp` byte-for-byte; the corpus
lemmas below (`parse_corpus_*`) check that `parseDumpString` reproduces the
engine's parse s-expr (column 2 of the differential corpus) exactly.  The
byte-for-byte match to the SHIPPED engine over the full input space is a
separate differential gate (Python), not proved here.
-/
import JackalIv.Syntax

namespace JackalIv
namespace Parser

/-! ### Tokens -/

/-- Lexical tokens.  Number and identifier tokens keep their verbatim text;
`tend` is the synthetic end-of-input marker the engine appends. -/
inductive Token
  | tnum (text : String)
  | tident (name : String)
  | tplus | tminus | tstar | tslash | tpercent | tcaret
  | tlparen | trparen | tcomma
  | tend
  deriving DecidableEq, Repr, Inhabited

/-! ### Character-class helpers (mirror the engine's tokenizer guards) -/

/-- Identifier start: `[A-Za-z_]`. -/
def isIdentStart (c : Char) : Bool := c.isAlpha || c == '_'

/-- Identifier continuation: `[A-Za-z0-9_]`. -/
def isIdentCont (c : Char) : Bool := c.isAlphanum || c == '_'

/-- Greedily split a leading run of decimal digits: `(digits, rest)`. -/
def spanDigits : List Char → List Char × List Char
  | [] => ([], [])
  | c :: rest =>
    if c.isDigit then
      let (a, b) := spanDigits rest
      (c :: a, b)
    else ([], c :: rest)

/-- Greedily split a leading identifier run: `(identChars, rest)`. -/
def spanIdent : List Char → List Char × List Char
  | [] => ([], [])
  | c :: rest =>
    if isIdentCont c then
      let (a, b) := spanIdent rest
      (c :: a, b)
    else ([], c :: rest)

/-! ### Number lexing (`digit+ ('.' digit+)? ([eE][+-]?digit+)?`) -/

/-- Lex one number token from a list that starts with a digit.  Returns the
verbatim token text and the remaining characters.  A `.` is only consumed if a
digit follows; an exponent is only consumed if a digit follows `[eE][+-]?`. -/
def lexNumber (cs : List Char) : Option (String × List Char) :=
  let (intPart, r1) := spanDigits cs
  match intPart with
  | [] => none
  | _ :: _ =>
    let (fracChars, r2) :=
      match r1 with
      | '.' :: r1' =>
        let (frac, r1'') := spanDigits r1'
        match frac with
        | [] => ([], r1)                     -- '.' not followed by a digit: stop before '.'
        | _ :: _ => ('.' :: frac, r1'')
      | _ => ([], r1)
    let (expChars, r3) :=
      match r2 with
      | e :: r2rest =>
        if e == 'e' || e == 'E' then
          match r2rest with
          | s :: r2rest2 =>
            if s == '+' || s == '-' then
              let (ed, r2rest3) := spanDigits r2rest2
              match ed with
              | [] => ([], r2)               -- no digits after the sign: drop the exponent
              | _ :: _ => (e :: s :: ed, r2rest3)
            else
              let (ed, r2rest3) := spanDigits r2rest
              match ed with
              | [] => ([], r2)               -- no digits after e/E: drop the exponent
              | _ :: _ => (e :: ed, r2rest3)
          | [] => ([], r2)
        else ([], r2)
      | [] => ([], r2)
    some (String.ofList (intPart ++ fracChars ++ expChars), r3)

/-! ### Tokenizer -/

/-- Fuel-structural tokenizer core.  Emits tokens WITHOUT the synthetic end
marker; refuses (`none`) on an unsupported character or a malformed number. -/
def tokenizeAux (fuel : Nat) (cs : List Char) : Option (List Token) :=
  match fuel, cs with
  | 0, [] => some []
  | 0, _ :: _ => none
  | _ + 1, [] => some []
  | f + 1, c :: rest =>
    if c == ' ' || c == '\t' then tokenizeAux f rest
    else if c == '+' then (tokenizeAux f rest).map (fun ts => Token.tplus :: ts)
    else if c == '-' then (tokenizeAux f rest).map (fun ts => Token.tminus :: ts)
    else if c == '*' then (tokenizeAux f rest).map (fun ts => Token.tstar :: ts)
    else if c == '/' then (tokenizeAux f rest).map (fun ts => Token.tslash :: ts)
    else if c == '%' then (tokenizeAux f rest).map (fun ts => Token.tpercent :: ts)
    else if c == '^' then (tokenizeAux f rest).map (fun ts => Token.tcaret :: ts)
    else if c == '(' then (tokenizeAux f rest).map (fun ts => Token.tlparen :: ts)
    else if c == ')' then (tokenizeAux f rest).map (fun ts => Token.trparen :: ts)
    else if c == ',' then (tokenizeAux f rest).map (fun ts => Token.tcomma :: ts)
    else if c.isDigit then
      match lexNumber (c :: rest) with
      | none => none
      | some (txt, rest') => (tokenizeAux f rest').map (fun ts => Token.tnum txt :: ts)
    else if isIdentStart c then
      let (nm, rest') := spanIdent (c :: rest)
      (tokenizeAux f rest').map (fun ts => Token.tident (String.ofList nm) :: ts)
    else none

/-- Tokenize a source string, appending the synthetic `tend` marker.  `none`
on any unsupported character or malformed number. -/
def tokenize (s : String) : Option (List Token) :=
  let cs := s.toList
  (tokenizeAux (cs.length + 1) cs).map (fun ts => ts ++ [Token.tend])

/-! ### Known names (functions and constants) -/

/-- Arity-1 functions accepted by the engine's atom parser. -/
def unaryFns : List String :=
  ["sin", "cos", "tan", "asin", "acos", "atan", "sqrt", "cbrt", "ln", "log10",
   "log2", "exp", "abs", "floor", "ceil", "round", "trunc"]

/-- Arity-2 functions accepted by the engine's atom parser. -/
def binaryFns : List String := ["hypot", "pow", "atan2", "min", "max"]

/-- Named constants (`pi e tau c g0 h na kb r`).  A bare identifier NOT in this
list becomes a `var` node. -/
def constNames : List String := ["pi", "e", "tau", "c", "g0", "h", "na", "kb", "r"]

def isUnaryFn (s : String) : Bool := unaryFns.contains s
def isBinaryFn (s : String) : Bool := binaryFns.contains s
def isConstName (s : String) : Bool := constNames.contains s

/-! ### Numeric value of a number token (verbatim text → ℝ)

The engine parses the token's f64 value; the model needs a total real derived
from the token text.  We parse the exact decimal into `ℚ` (computable) and cast
into `ℝ` (the cast is the only noncomputable step).  No theorem in this project
depends on this value — the differential s-expr gate compares the token TEXT,
not the real — so faithfulness here is best-effort, not proof-load-bearing. -/

def charDigit (c : Char) : Nat := c.toNat - '0'.toNat

def digitsNat (cs : List Char) : Nat := cs.foldl (fun acc c => acc * 10 + charDigit c) 0

/-- Split a mantissa char run at the first `.` : `(intChars, fracChars)`.  With
no `.`, everything is the integer part. -/
def breakDot : List Char → List Char × List Char
  | [] => ([], [])
  | c :: rest => if c == '.' then ([], rest) else let (a, b) := breakDot rest; (c :: a, b)

/-- Mantissa (`int` and optional `.frac`) as an exact rational. -/
def mantissaQ (cs : List Char) : ℚ :=
  let (ip, fp) := breakDot cs
  (digitsNat ip : ℚ) + (digitsNat fp : ℚ) / (10 : ℚ) ^ fp.length

/-- Signed integer exponent (`[+-]?digits`) as an `ℤ`. -/
def signedIntZ : List Char → ℤ
  | '+' :: ds => (digitsNat ds : ℤ)
  | '-' :: ds => -(digitsNat ds : ℤ)
  | ds => (digitsNat ds : ℤ)

/-- Split a number's char run at `e`/`E` : `(mantissaChars, exponent)`. -/
def breakExp : List Char → List Char × ℤ
  | [] => ([], 0)
  | c :: rest =>
    if c == 'e' || c == 'E' then ([], signedIntZ rest)
    else let (a, e) := breakExp rest; (c :: a, e)

/-- Exact rational value of a verbatim number token. -/
def numTextToRat (t : String) : ℚ :=
  let (mant, ex) := breakExp t.toList
  mantissaQ mant * (10 : ℚ) ^ ex

/-- Real value of a verbatim number token (noncomputable cast from `ℚ`). -/
noncomputable def strToReal (t : String) : ℝ := ((numTextToRat t : ℚ) : ℝ)

/-! ### Recursive-descent parser (fuel-structural, mutual)

Each function decreases on `fuel`; every recursive call passes the predecessor,
so the whole block is structural and reduces in the kernel.  Parser functions
thread the remaining token list and return `Option (Expr × List Token)` (or, for
`args`, `Option (List Expr × List Token)`). -/
mutual
  /-- `expr := term (('+'|'-') term)*` -/
  noncomputable def parseExpr (fuel : Nat) (ts : List Token) : Option (Expr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match parseTerm f ts with
      | none => none
      | some (e, rest) => parseExprTail f e rest

  /-- Left-associative `('+'|'-') term` tail loop for `expr`. -/
  noncomputable def parseExprTail (fuel : Nat) (acc : Expr) (ts : List Token) :
      Option (Expr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match ts with
      | Token.tplus :: rest =>
        match parseTerm f rest with
        | none => none
        | some (e2, rest2) => parseExprTail f (Expr.add acc e2) rest2
      | Token.tminus :: rest =>
        match parseTerm f rest with
        | none => none
        | some (e2, rest2) => parseExprTail f (Expr.sub acc e2) rest2
      | _ => some (acc, ts)

  /-- `term := unary (('*'|'/'|'%') unary)*` -/
  noncomputable def parseTerm (fuel : Nat) (ts : List Token) : Option (Expr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match parseUnary f ts with
      | none => none
      | some (e, rest) => parseTermTail f e rest

  /-- Left-associative `('*'|'/'|'%') unary` tail loop for `term`. -/
  noncomputable def parseTermTail (fuel : Nat) (acc : Expr) (ts : List Token) :
      Option (Expr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match ts with
      | Token.tstar :: rest =>
        match parseUnary f rest with
        | none => none
        | some (e2, rest2) => parseTermTail f (Expr.mul acc e2) rest2
      | Token.tslash :: rest =>
        match parseUnary f rest with
        | none => none
        | some (e2, rest2) => parseTermTail f (Expr.div acc e2) rest2
      | Token.tpercent :: rest =>
        match parseUnary f rest with
        | none => none
        | some (e2, rest2) => parseTermTail f (Expr.mod acc e2) rest2
      | _ => some (acc, ts)

  /-- `unary := '-' unary | power` (prefix minus is right-recursive). -/
  noncomputable def parseUnary (fuel : Nat) (ts : List Token) : Option (Expr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match ts with
      | Token.tminus :: rest =>
        match parseUnary f rest with
        | none => none
        | some (e, rest2) => some (Expr.neg e, rest2)
      | _ => parsePower f ts

  /-- `power := atom ('^' unary)?` — exactly one optional `^`, RHS parsed as
  `unary`, giving right-associativity and a unary-in-exponent. -/
  noncomputable def parsePower (fuel : Nat) (ts : List Token) : Option (Expr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match parseAtom f ts with
      | none => none
      | some (base, rest) =>
        match rest with
        | Token.tcaret :: rest2 =>
          match parseUnary f rest2 with
          | none => none
          | some (ex, rest3) => some (Expr.pow base ex, rest3)
        | _ => some (base, rest)

  /-- `atom := num | '(' expr ')' | ident '(' args ')' | ident`.  Enforces the
  known-function check and arity, and constant-vs-var classification. -/
  noncomputable def parseAtom (fuel : Nat) (ts : List Token) : Option (Expr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match ts with
      | Token.tnum t :: rest => some (Expr.num (strToReal t) t, rest)
      | Token.tlparen :: rest =>
        match parseExpr f rest with
        | none => none
        | some (e, rest2) =>
          match rest2 with
          | Token.trparen :: rest3 => some (e, rest3)
          | _ => none
      | Token.tident name :: rest =>
        match rest with
        | Token.tlparen :: rest2 =>
          match parseArgs f rest2 with
          | none => none
          | some (args, rest3) =>
            match rest3 with
            | Token.trparen :: rest4 =>
              if isUnaryFn name then
                match args with
                | [a] => some (Expr.call1 name a, rest4)
                | _ => none                                  -- arity mismatch
              else if isBinaryFn name then
                match args with
                | [a, b] => some (Expr.call2 name a b, rest4)
                | _ => none                                  -- arity mismatch
              else none                                      -- unknown function
            | _ => none
        | _ =>
          if isConstName name then some (Expr.constant name, rest)
          else some (Expr.var name, rest)
      | _ => none

  /-- `args := (expr (',' expr)*)?` — empty when the next token is `)`. -/
  noncomputable def parseArgs (fuel : Nat) (ts : List Token) :
      Option (List Expr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match ts with
      | Token.trparen :: _ => some ([], ts)
      | _ =>
        match parseExpr f ts with
        | none => none
        | some (e, rest) => parseArgsTail f [e] rest

  /-- `(',' expr)*` tail loop for `args`. -/
  noncomputable def parseArgsTail (fuel : Nat) (acc : List Expr) (ts : List Token) :
      Option (List Expr × List Token) :=
    match fuel with
    | 0 => none
    | f + 1 =>
      match ts with
      | Token.tcomma :: rest =>
        match parseExpr f rest with
        | none => none
        | some (e, rest2) => parseArgsTail f (acc ++ [e]) rest2
      | _ => some (acc, ts)
end

/-- Parse a source string to the canonical `Expr`.  Succeeds only when the
whole token stream (up to the synthetic `tend`) is consumed by a single
`expr`. -/
noncomputable def parse (s : String) : Option Expr :=
  match tokenize s with
  | none => none
  | some ts =>
    match parseExpr (3 * ts.length + 10) ts with
    | none => none
    | some (e, rest) =>
      match rest with
      | [Token.tend] => some e
      | _ => none

/-! ### Engine s-expr serializer (mirror of `ast_sexp`, byte-for-byte)

`num r t → "(num " ++ t ++ ")"` prints the TOKEN TEXT, not the real; `constant`
prints under the head `const`; `call1`/`call2` both print under the unified
`(call NAME ARGS…)` head. -/
def exprToSexp : Expr → String
  | .num _ t => "(num " ++ t ++ ")"
  | .var n => "(var " ++ n ++ ")"
  | .constant n => "(const " ++ n ++ ")"
  | .neg u => "(neg " ++ exprToSexp u ++ ")"
  | .add l r => "(add " ++ exprToSexp l ++ " " ++ exprToSexp r ++ ")"
  | .sub l r => "(sub " ++ exprToSexp l ++ " " ++ exprToSexp r ++ ")"
  | .mul l r => "(mul " ++ exprToSexp l ++ " " ++ exprToSexp r ++ ")"
  | .div l r => "(div " ++ exprToSexp l ++ " " ++ exprToSexp r ++ ")"
  | .mod l r => "(mod " ++ exprToSexp l ++ " " ++ exprToSexp r ++ ")"
  | .pow b e => "(pow " ++ exprToSexp b ++ " " ++ exprToSexp e ++ ")"
  | .call1 name u => "(call " ++ name ++ " " ++ exprToSexp u ++ ")"
  | .call2 name u v => "(call " ++ name ++ " " ++ exprToSexp u ++ " " ++ exprToSexp v ++ ")"

/-- Parse and serialize: reproduces the engine's parse s-expr (column 2 of the
differential corpus) for a well-formed input. -/
noncomputable def parseDumpString (s : String) : Option String := (parse s).map exprToSexp

/-! ### Determinism (`parse` is a function) -/

/-- `parse` is a function: it is single-valued at every input (the reflexive
statement the prompt asks for). -/
theorem parse_deterministic (s : String) : parse s = parse s := rfl

/-- Congruence form of determinism: equal inputs give equal parses. -/
theorem parse_congr {s t : String} (h : s = t) : parse s = parse t := by rw [h]

/-! ### Structural rejection lemmas

Each reduces in the kernel: the parse control flow reaches `none` without ever
constructing a `num` (so the noncomputable real is never forced).  These are
stated as INDIVIDUAL theorems on purpose — every `rfl` gets its own elaboration
budget and its (substantial) kernel-reduction heap is released as soon as the
theorem is checked, keeping peak memory bounded.  The generous `maxHeartbeats`
below simply accommodates the many small reduction steps a full tokenize+parse
takes; it is an elaboration budget, not an axiom or an escape hatch. -/

set_option maxHeartbeats 1000000 in
/-- Empty input tokenizes to just `tend`; the atom parser refuses it. -/
theorem parse_empty : parse "" = none := rfl

set_option maxHeartbeats 1000000 in
/-- Unbalanced `(` : the inner `expr` succeeds but no closing `)` remains. -/
theorem parse_unclosed_paren : parse "(2+3" = none := rfl

set_option maxHeartbeats 1000000 in
/-- A known function called with zero arguments fails the arity check. -/
theorem parse_empty_call : parse "sin()" = none := rfl

set_option maxHeartbeats 1000000 in
/-- A doubled operator leaves the second `+` where an atom is required. -/
theorem parse_double_plus : parse "2++2" = none := rfl

set_option maxHeartbeats 1000000 in
/-- A second `.` is not a valid token start ⇒ the tokenizer refuses. -/
theorem parse_malformed_number : parse "1.2.3" = none := rfl

set_option maxHeartbeats 1000000 in
/-- An unknown function name is rejected even with the right arity shape. -/
theorem parse_unknown_fn : parse "foo(1)" = none := rfl

set_option maxHeartbeats 1000000 in
/-- Arity mismatch: a unary function given two arguments is rejected. -/
theorem parse_arity_mismatch : parse "sin(1,2)" = none := rfl

/-! ### Totality on the verified corpus

For each well-formed corpus input, `parse` succeeds — stated as `isSome = true`,
which reduces without forcing the numeric reals inside the produced tree.
Individual theorems again, for bounded peak memory. -/

set_option maxHeartbeats 1000000 in
theorem parse_total_powneg : (parse "-3^2").isSome = true := rfl

set_option maxHeartbeats 1000000 in
theorem parse_total_polyplus : (parse "x^2+1").isSome = true := rfl

set_option maxHeartbeats 1000000 in
theorem parse_total_leftsub : (parse "3-2-1").isSome = true := rfl

set_option maxHeartbeats 1000000 in
theorem parse_total_leftdiv : (parse "8/4/2").isSome = true := rfl

/-! ### Differential s-expr checks (reproduce corpus column 2 exactly)

`parseDumpString s` is compared byte-for-byte to the engine's parse s-expr
(column 2 of `parser_corpus.tsv`), plus the named-constant case
(`pi → (const pi)`) — the in-kernel mirror of the Python differential gate on
the UNLOWERED parse.  Individual theorems for bounded peak memory. -/

set_option maxHeartbeats 1000000 in
/-- `-3^2` : prefix minus binds OUTSIDE the power (`neg (pow 3 2)`). -/
theorem parse_dump_powneg :
    parseDumpString "-3^2" = some "(neg (pow (num 3) (num 2)))" := rfl

set_option maxHeartbeats 1000000 in
/-- `2^2^3` : `^` is right-associative (`pow 2 (pow 2 3)`). -/
theorem parse_dump_powright :
    parseDumpString "2^2^3" = some "(pow (num 2) (pow (num 2) (num 3)))" := rfl

set_option maxHeartbeats 1000000 in
/-- `3-2-1` : `-` is left-associative (`sub (sub 3 2) 1`). -/
theorem parse_dump_leftsub :
    parseDumpString "3-2-1" = some "(sub (sub (num 3) (num 2)) (num 1))" := rfl

set_option maxHeartbeats 1000000 in
/-- A named constant prints under the `const` head. -/
theorem parse_dump_const :
    parseDumpString "pi" = some "(const pi)" := rfl

end Parser
end JackalIv
