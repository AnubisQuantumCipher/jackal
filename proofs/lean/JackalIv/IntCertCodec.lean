/-
JackalIv/IntCertCodec.lean — public certified integrate-bound-cert lane (v1.7).

Wire codec for the v1.7 `bound_step` composition artifact
(`jackal-int-cert v1`).  Line grammar, one LF per line:

  jackal-int-cert v<n>
  model <str>
  checker <str>
  producer <str-or-empty>
  status <str>
  expr <sexp>
  source <opaque-or-empty>
  request <lo> <hi> <tol>
  degree <n>
  root <id>
  output <lo> <hi>
  tree <id> <kind> dom[<a>,<b>] out[<lo>,<hi>] children[<c0>,...]
  ...                                (ids strictly ascending)
  cert <tree-id> <role> lines <n>
  <n verbatim lines: one complete embedded `jackal-eval-cert v2`>
  ...                                (roles in canonical per-kind order)
  end

All rationals are the canonical `Cert.parseRatCanon` grammar (reduced `p/q`,
no `/1`, no decimal point, no exponent, no leading zeros); every violation
refuses with reason class `noncanonical-value`; structural violations refuse
with `malformed-artifact`.  Embedded certificate blocks are handed VERBATIM
to the existing proved `Cert.parseCert`.

No `sorry`, no axiom, no `native_decide`, no `@[implemented_by]`.
-/
import JackalIv.CertCodec
import JackalIv.IntCertTypes

namespace JackalIv.IntCert

open JackalIv

/-! ### Small parsing helpers over the existing codec primitives -/

private def strOf (cs : List Char) : String := String.ofList cs

/-- Parse one canonical rational or refuse with `noncanonical-value`. -/
private def ratOr (field : String) (cs : List Char) : Except String ℚ :=
  match Cert.parseRatCanon cs with
  | some q => .ok q
  | none => .error ("noncanonical-value:" ++ field)

/-- Parse one canonical natural or refuse with `malformed-artifact`. -/
private def natOr (field : String) (cs : List Char) : Except String Nat :=
  match Cert.parseNatCanon cs with
  | some n => .ok n
  | none => .error ("malformed-artifact:" ++ field)

/-- Strip a `key ` prefix or refuse. -/
private def keyed (key : String) (line : List Char) :
    Except String (List Char) :=
  match Cert.stripPrefix (key.toList ++ [' ']) line with
  | some rest => .ok rest
  | none => .error ("malformed-artifact:expected-" ++ key)

/-- `key` line holding an opaque (possibly empty) string. -/
private def keyedStr (key : String) (line : List Char) :
    Except String String :=
  match Cert.stripPrefix (key.toList ++ [' ']) line with
  | some rest => .ok (strOf rest)
  | none =>
      -- allow a bare `key` line for an empty value
      if line = key.toList then .ok ""
      else .error ("malformed-artifact:expected-" ++ key)

/-- Canonical role order per leaf kind (wire-level mirror of `roleSpecs`). -/
def roleNames (kind : String) : List String :=
  if kind = "range" then ["f"]
  else if kind = "taylor2" then ["f", "f1", "f2", "fm"]
  else if kind = "taylor4" then ["f", "f1", "f2", "f3", "f4", "fm", "f2m"]
  else []

/-! ### Line parsers -/

/-- Magic line: `jackal-int-cert v<n>`. -/
def parseIntCertMagic (line : List Char) : Except String Nat :=
  match Cert.stripPrefix "jackal-int-cert v".toList line with
  | some rest => natOr "schema-version" rest
  | none => .error "malformed-artifact:expected-magic"

/-- `request <lo> <hi> <tol>`. -/
def parseRequestLine (line : List Char) : Except String (ℚ × ℚ × ℚ) := do
  let rest ← keyed "request" line
  match Cert.splitOn ' ' rest with
  | [lo, hi, tol] => do
      let qlo ← ratOr "request-lo" lo
      let qhi ← ratOr "request-hi" hi
      let qtol ← ratOr "request-tol" tol
      return (qlo, qhi, qtol)
  | _ => .error "malformed-artifact:request-arity"

/-- `tree <id> <kind> dom[<a>,<b>] out[<lo>,<hi>] children[...]`. -/
def parseTreeLine (line : List Char) : Except String TreeNode := do
  let rest ← keyed "tree" line
  match Cert.splitOn ' ' rest with
  | [idTok, kindTok, domTok, outTok, chTok] => do
      let id ← natOr "tree-id" idTok
      let dom ← match Cert.parseBracketRats2 "dom" domTok with
        | some p => .ok p
        | none => .error "noncanonical-value:tree-dom"
      let out ← match Cert.parseBracketRats2 "out" outTok with
        | some p => .ok p
        | none => .error "noncanonical-value:tree-out"
      let ch ← match Cert.parseBracketNats "children" chTok with
        | some l => .ok l
        | none => .error "malformed-artifact:tree-children"
      return { id := id, kind := strOf kindTok, a := dom.1, b := dom.2,
               lo := out.1, hi := out.2, children := ch, certs := [] }
  | _ => .error "malformed-artifact:tree-arity"

/-- `cert <tree-id> <role> lines <n>` block header. -/
def parseCertHeaderLine (line : List Char) :
    Except String (Nat × String × Nat) := do
  let rest ← keyed "cert" line
  match Cert.splitOn ' ' rest with
  | [tidTok, roleTok, kw, nTok] => do
      if kw ≠ "lines".toList then
        .error "malformed-artifact:cert-header"
      else do
        let tid ← natOr "cert-tree-id" tidTok
        let n ← natOr "cert-lines" nTok
        return (tid, strOf roleTok, n)
  | _ => .error "malformed-artifact:cert-arity"

/-! ### Artifact assembly -/

/-- Attach one embedded certificate to the tree node `tid`, enforcing the
canonical role order for that node's kind. -/
def attachCert (tree : List TreeNode) (tid : Nat) (role : String)
    (c : EvalCert) : Except String (List TreeNode) :=
  match findTree tree tid with
  | none => .error "malformed-artifact:cert-ref"
  | some t =>
      let expected := roleNames t.kind
      match expected[t.certs.length]? with
      | none => .error "malformed-artifact:role-count"
      | some want =>
          if role ≠ want then .error "malformed-artifact:role-order"
          else
            .ok (tree.map (fun u =>
              if u.id == tid then { u with certs := u.certs ++ [c] } else u))

/-- Take `n` lines verbatim; refuse if fewer remain. -/
def takeLines : Nat → List (List Char) →
    Except String (List (List Char) × List (List Char))
  | 0, rest => .ok ([], rest)
  | _ + 1, [] => .error "malformed-artifact:embedded-truncated"
  | n + 1, l :: rest => do
      let (taken, remaining) ← takeLines n rest
      return (l :: taken, remaining)

/-- Parse the tree-line section (strictly ascending ids). -/
def parseTreeLines : List (List Char) → List TreeNode → Option Nat →
    Except String (List TreeNode × List (List Char))
  | [], acc, _ => .ok (acc.reverse, [])
  | l :: rest, acc, lastId =>
      if (Cert.stripPrefix "tree ".toList l).isSome then do
        let t ← parseTreeLine l
        match lastId with
        | some prev =>
            if t.id ≤ prev then .error "malformed-artifact:tree-order"
            else parseTreeLines rest (t :: acc) (some t.id)
        | none => parseTreeLines rest (t :: acc) (some t.id)
      else
        .ok (acc.reverse, l :: rest)

/-- Parse the cert-block section, attaching to tree nodes, until `end`. -/
def parseCertBlocks : Nat → List (List Char) → List TreeNode →
    Except String (List TreeNode)
  | 0, _, _ => .error "malformed-artifact:fuel"
  | _ + 1, [], _ => .error "malformed-artifact:missing-end"
  | fuel + 1, l :: rest, tree =>
      if l = "end".toList then
        match rest with
        | [[]] => .ok tree
        | [] => .error "malformed-artifact:missing-trailing-newline"
        | _ => .error "malformed-artifact:trailing-bytes"
      else if (Cert.stripPrefix "cert ".toList l).isSome then do
        let (tid, role, n) ← parseCertHeaderLine l
        let (block, remaining) ← takeLines n rest
        -- hand the block to the existing PROVED line-level parser directly
        -- (the trailing [] mirrors the embedded certificate's final newline)
        match Cert.parseCertLines (block ++ [[]]) with
        | .error e => .error ("malformed-artifact:embedded:" ++ e)
        | .ok (hdr, nodes) => do
            let tree' ← attachCert tree tid role ⟨hdr, nodes⟩
            parseCertBlocks fuel remaining tree'
      else .error "malformed-artifact:unexpected-line"

/-- The full artifact parser. -/
def parseIntCert (s : String) : Except String (IntHeader × List TreeNode) := do
  -- stack-safe line split (core `String.splitOn` is iteration-friendly; the
  -- per-character recursive `Cert.splitOn` overflows the interpreter on
  -- multi-hundred-KB artifacts)
  match (s.splitOn "\n").map String.toList with
  | lmagic :: lmodel :: lchecker :: lproducer :: lstatus :: lexpr :: lsource ::
      lrequest :: ldegree :: lroot :: loutput :: rest => do
      let sv ← parseIntCertMagic lmagic
      let model ← keyedStr "model" lmodel
      let checker ← keyedStr "checker" lchecker
      let producer ← keyedStr "producer" lproducer
      let status ← keyedStr "status" lstatus
      let expr ← keyedStr "expr" lexpr
      let source ← keyedStr "source" lsource
      let (qlo, qhi, qtol) ← parseRequestLine lrequest
      let degree ← match Cert.stripPrefix "degree ".toList ldegree with
        | some r => natOr "degree" r
        | none => .error "malformed-artifact:expected-degree"
      let rootId ← match Cert.stripPrefix "root ".toList lroot with
        | some r => natOr "root" r
        | none => .error "malformed-artifact:expected-root"
      let out ← match Cert.stripPrefix "output ".toList loutput with
        | some r =>
            (match Cert.splitOn ' ' r with
             | [lo, hi] => do
                let qolo ← ratOr "output-lo" lo
                let qohi ← ratOr "output-hi" hi
                Except.ok (qolo, qohi)
             | _ => .error "malformed-artifact:output-arity")
        | none => .error "malformed-artifact:expected-output"
      let (tree, remaining) ← parseTreeLines rest [] none
      let tree ← parseCertBlocks (remaining.length + 1) remaining tree
      return ({ schema_version := sv, model_const_version := model,
                checker_identity := checker, producer_identity := producer,
                status_class := status, expr_commitment := expr,
                source_commitment := source, req_lo := qlo, req_hi := qhi,
                tol := qtol, degree := degree, root_id := rootId,
                out_lo := out.1, out_hi := out.2 }, tree)
  | _ => .error "malformed-artifact:truncated-header"

end JackalIv.IntCert
