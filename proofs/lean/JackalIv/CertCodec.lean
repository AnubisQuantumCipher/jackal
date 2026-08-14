/-
JackalIv/CertCodec.lean — the canonical string codec (schema v1, phase 2).

`emitCert : Header → List Node → String` serializes a structured certificate to
the canonical, deterministic, line-based `jackal-eval-cert v1` grammar of
`CERT_DESIGN.md`; `parseCert : String → Except String (Header × List Node)`
parses it back, REJECTING every malformation the design lists (non-canonical
rational, dup/reordered/missing header key, dup/unknown/reordered node field,
non-ascending or duplicate node id, forward/self child ref, trailing bytes).

Everything is genuinely COMPUTABLE `List Char`/`Nat`/`Int`/`Rat`/`String`
plumbing — NO `Real`, NO `noncomputable`, NO `native_decide`/`@[implemented_by]`
— so the same proved `parseCert` runs in the `jackal_cert_check` executable and
the reduction lemmas discharge by `decide`.

Design fidelity notes (the phase-2 grammar sketch is completed here, since it is
literally incomplete — it carries no slot for a node's intended `value`):
  * a `val <rat>` scalar field is added (num_exact/num_rounded/const_rounded),
    placed in the fixed field order right after `out`;
  * scalar fields are `key <tok>` (`val`,`n`,`den`,`name`); tuple fields are
    `key[a,b,...]` (`children`,`out`,`f`,`p`,`stage`) — matching the grammar;
  * canonical `ℚ`/`ℤ`/`ℕ` tokens exactly as CERT_DESIGN §"Canonical string
    grammar" (reduced, den≥2, no leading zeros, `0` not `0/1`, no nan/inf/./+);
  * `source_commitment` is base64 of its UTF-8 bytes (delimiter-safe).

Proved here:
  * `parseNatCanon_natDigits` / `parseIntCanon_intToStr` / `parseRatCanon_ratToStr`
    — the general canonical numeric codec inverses;
  * `parse_emit_roundtrip` — `parseCert (emitCert hdr nodes) = .ok (hdr, nodes)`
    for the well-formed class (stated as `RoundtripWF`);
  * a battery of REJECTION lemmas (dup header key, non-canonical rat, trailing
    bytes, dup node id, forward child ref) discharged by `decide`.

No `sorry`/`admit`/axiom/`native_decide`/`unsafe`/`@[implemented_by]`.
-/
import JackalIv.CertCheck

namespace JackalIv.Cert
open JackalIv

/-! ### digit chars -/

def digitChar : Nat → Char
  | 0 => '0' | 1 => '1' | 2 => '2' | 3 => '3' | 4 => '4'
  | 5 => '5' | 6 => '6' | 7 => '7' | 8 => '8' | _ => '9'

def digitCharVal (c : Char) : Option Nat :=
  if c = '0' then some 0 else if c = '1' then some 1 else if c = '2' then some 2
  else if c = '3' then some 3 else if c = '4' then some 4 else if c = '5' then some 5
  else if c = '6' then some 6 else if c = '7' then some 7 else if c = '8' then some 8
  else if c = '9' then some 9 else none

lemma digitCharVal_digitChar {d : Nat} (h : d < 10) : digitCharVal (digitChar d) = some d := by
  interval_cases d <;> rfl

/-! ### nat digits (structural fuel recursion so it reduces under `decide`) -/

def natDigitsAux : Nat → Nat → List Char
  | 0, _ => []
  | fuel + 1, n =>
      if n < 10 then [digitChar n]
      else natDigitsAux fuel (n / 10) ++ [digitChar (n % 10)]

/-- Fuel independence: as long as `fuel > n`, the result is the same. -/
lemma natDigitsAux_indep : ∀ (n f1 f2 : Nat), n < f1 → n < f2 →
    natDigitsAux f1 n = natDigitsAux f2 n := by
  intro n
  induction n using Nat.strong_induction_on with
  | _ n ih =>
    intro f1 f2 h1 h2
    obtain ⟨k1, rfl⟩ : ∃ k, f1 = k + 1 := ⟨f1 - 1, by omega⟩
    obtain ⟨k2, rfl⟩ : ∃ k, f2 = k + 1 := ⟨f2 - 1, by omega⟩
    simp only [natDigitsAux]
    by_cases h : n < 10
    · rw [if_pos h, if_pos h]
    · rw [if_neg h, if_neg h]
      have hdiv : n / 10 < n := Nat.div_lt_self (by omega) (by norm_num)
      rw [ih (n / 10) hdiv k1 k2 (by omega) (by omega)]

def natDigits (n : Nat) : List Char := natDigitsAux (n + 1) n

/-- Clean recursion equation for `natDigits`. -/
lemma natDigits_unfold (n : Nat) :
    natDigits n = if n < 10 then [digitChar n]
                  else natDigits (n / 10) ++ [digitChar (n % 10)] := by
  unfold natDigits
  conv_lhs => rw [natDigitsAux]
  by_cases h : n < 10
  · rw [if_pos h, if_pos h]
  · rw [if_neg h, if_neg h]
    have hdiv : n / 10 < n := Nat.div_lt_self (by omega) (by norm_num)
    rw [natDigitsAux_indep (n / 10) n (n / 10 + 1) (by omega) (by omega)]

def dstep (acc : Option Nat) (c : Char) : Option Nat :=
  match acc, digitCharVal c with
  | some a, some d => some (a * 10 + d)
  | _, _ => none

def parseDigitsL (cs : List Char) : Option Nat := cs.foldl dstep (some 0)

lemma parseDigitsL_natDigits : ∀ (n acc : Nat),
    (natDigits n).foldl dstep (some acc)
      = some (acc * 10 ^ (natDigits n).length + n) := by
  intro n
  induction n using Nat.strong_induction_on with
  | _ n ih =>
    intro acc
    rw [natDigits_unfold]
    by_cases h : n < 10
    · rw [if_pos h]
      simp [dstep, digitCharVal_digitChar h]
    · rw [if_neg h]
      have hmod : n % 10 < 10 := Nat.mod_lt _ (by omega)
      have hdiv : n / 10 < n := Nat.div_lt_self (by omega) (by norm_num)
      rw [List.foldl_append, ih (n / 10) hdiv acc]
      simp only [List.foldl_cons, List.foldl_nil, dstep, digitCharVal_digitChar hmod,
        List.length_append, List.length_cons, List.length_nil]
      congr 1
      generalize (natDigits (n / 10)).length = L
      have hdm : n / 10 * 10 + n % 10 = n := by rw [Nat.mul_comm]; exact Nat.div_add_mod n 10
      calc (acc * 10 ^ L + n / 10) * 10 + n % 10
          = acc * (10 ^ L * 10) + (n / 10 * 10 + n % 10) := by ring
        _ = acc * 10 ^ (L + 1) + n := by rw [hdm, pow_succ]

/-- Canonical nat parse: nonempty, all digits, no leading zeros. -/
def parseNatCanon (cs : List Char) : Option Nat :=
  if cs.isEmpty then none
  else
    match parseDigitsL cs with
    | some n => if natDigits n = cs then some n else none
    | none => none

lemma natDigits_ne_nil (n : Nat) : natDigits n ≠ [] := by
  rw [natDigits_unfold]; split <;> simp

lemma parseDigitsL_eq (n : Nat) : parseDigitsL (natDigits n) = some n := by
  unfold parseDigitsL
  rw [parseDigitsL_natDigits n 0]; simp

lemma parseNatCanon_natDigits (n : Nat) : parseNatCanon (natDigits n) = some n := by
  unfold parseNatCanon
  have hne : (natDigits n).isEmpty = false := by
    cases h : natDigits n with
    | nil => exact absurd h (natDigits_ne_nil n)
    | cons => rfl
  rw [hne]
  simp only [Bool.false_eq_true, if_false]
  rw [parseDigitsL_eq n]
  simp

/-! ### digit-membership facts about `natDigits` -/

lemma natDigits_mem_digit : ∀ (n : Nat), ∀ c ∈ natDigits n, digitCharVal c ≠ none := by
  intro n
  induction n using Nat.strong_induction_on with
  | _ n ih =>
    intro c hc
    rw [natDigits_unfold] at hc
    by_cases h : n < 10
    · rw [if_pos h] at hc
      simp only [List.mem_singleton] at hc
      subst hc; rw [digitCharVal_digitChar h]; simp
    · rw [if_neg h, List.mem_append] at hc
      have hdiv : n / 10 < n := Nat.div_lt_self (by omega) (by norm_num)
      rcases hc with hc | hc
      · exact ih (n / 10) hdiv c hc
      · simp only [List.mem_singleton] at hc
        subst hc
        have hmod : n % 10 < 10 := Nat.mod_lt _ (by omega)
        rw [digitCharVal_digitChar hmod]; simp

lemma natDigits_ne_neg (n : Nat) : ∀ c ∈ natDigits n, c ≠ '-' := by
  intro c hc h; have := natDigits_mem_digit n c hc; rw [h] at this; exact this rfl

lemma natDigits_ne_slash (n : Nat) : ∀ c ∈ natDigits n, c ≠ '/' := by
  intro c hc h; have := natDigits_mem_digit n c hc; rw [h] at this; exact this rfl

/-! ### int codec -/

def intToStr (i : Int) : List Char :=
  if i < 0 then '-' :: natDigits i.natAbs else natDigits i.natAbs

def parseIntCanon (cs : List Char) : Option Int :=
  match cs with
  | [] => none
  | c :: rest =>
      if c = '-' then
        (parseNatCanon rest).bind (fun n => if n = 0 then none else some (-(n : Int)))
      else (parseNatCanon (c :: rest)).map (fun n => (n : Int))

lemma intToStr_no_slash (i : Int) : ∀ c ∈ intToStr i, c ≠ '/' := by
  intro c hc
  unfold intToStr at hc
  split at hc
  · rcases List.mem_cons.mp hc with h | h
    · subst h; decide
    · exact natDigits_ne_slash _ c h
  · exact natDigits_ne_slash _ c hc

lemma parseIntCanon_intToStr (i : Int) : parseIntCanon (intToStr i) = some i := by
  unfold intToStr
  by_cases hlt : i < 0
  · rw [if_pos hlt]
    have hne : i.natAbs ≠ 0 := by omega
    simp only [parseIntCanon, reduceIte, parseNatCanon_natDigits, Option.bind_some, if_neg hne]
    congr 1; omega
  · rw [if_neg hlt]
    have hnn := natDigits_ne_nil i.natAbs
    cases hd : natDigits i.natAbs with
    | nil => exact absurd hd hnn
    | cons c cs =>
      have hcne : c ≠ '-' := natDigits_ne_neg i.natAbs c (by rw [hd]; exact List.mem_cons_self)
      simp only [parseIntCanon, if_neg hcne]
      rw [← hd, parseNatCanon_natDigits]
      show some ((i.natAbs : Int)) = some i
      congr 1; omega

/-! ### slash splitter -/

def splitOnSlash : List Char → List Char × Option (List Char)
  | [] => ([], none)
  | c :: cs =>
      if c = '/' then ([], some cs)
      else match splitOnSlash cs with
           | (a, b) => (c :: a, b)

lemma splitOnSlash_no_slash {a : List Char} (h : ∀ c ∈ a, c ≠ '/') :
    splitOnSlash a = (a, none) := by
  induction a with
  | nil => rfl
  | cons c cs ih =>
      unfold splitOnSlash
      rw [if_neg (h c List.mem_cons_self)]
      rw [ih (fun x hx => h x (List.mem_cons_of_mem c hx))]

lemma splitOnSlash_append {a b : List Char} (h : ∀ c ∈ a, c ≠ '/') :
    splitOnSlash (a ++ '/' :: b) = (a, some b) := by
  induction a with
  | nil => simp [splitOnSlash]
  | cons c cs ih =>
      simp only [List.cons_append]
      unfold splitOnSlash
      rw [if_neg (h c List.mem_cons_self)]
      rw [ih (fun x hx => h x (List.mem_cons_of_mem c hx))]

/-! ### rat codec -/

def ratToStr (q : ℚ) : List Char :=
  if q.den = 1 then intToStr q.num
  else intToStr q.num ++ ('/' :: natDigits q.den)

def parseRatCanon (cs : List Char) : Option ℚ :=
  match splitOnSlash cs with
  | (numPart, none) => (parseIntCanon numPart).map (fun i => (i : ℚ))
  | (numPart, some denPart) =>
      (parseIntCanon numPart).bind (fun num =>
        (parseNatCanon denPart).bind (fun den =>
          if 2 ≤ den ∧ Nat.Coprime num.natAbs den then some (Rat.divInt num den) else none))

lemma parseRatCanon_ratToStr (q : ℚ) : parseRatCanon (ratToStr q) = some q := by
  unfold ratToStr
  by_cases hd : q.den = 1
  · rw [if_pos hd]
    unfold parseRatCanon
    rw [splitOnSlash_no_slash (intToStr_no_slash q.num)]
    dsimp only
    rw [parseIntCanon_intToStr]
    show some ((q.num : ℚ)) = some q
    congr 1
    rw [← Rat.num_divInt_den q, hd]
    simp
  · rw [if_neg hd]
    unfold parseRatCanon
    rw [splitOnSlash_append (intToStr_no_slash q.num)]
    dsimp only
    rw [parseIntCanon_intToStr]
    simp only [Option.bind_some]
    rw [parseNatCanon_natDigits]
    simp only [Option.bind_some]
    have h2 : 2 ≤ q.den := by have := q.den_pos; omega
    have hcop : Nat.Coprime q.num.natAbs q.den := q.reduced
    rw [if_pos ⟨h2, hcop⟩, Rat.num_divInt_den]



/-! ### generic splitter and joiner over `List Char` -/

def splitOn (sep : Char) : List Char → List (List Char)
  | [] => [[]]
  | c :: cs =>
      if c = sep then [] :: splitOn sep cs
      else match splitOn sep cs with
           | l :: ls => (c :: l) :: ls
           | [] => [[c]]

def joinSep (sep : Char) : List (List Char) → List Char
  | [] => []
  | [t] => t
  | t :: ts => t ++ sep :: joinSep sep ts

/-! ### base64 for the opaque source commitment -/

def b64Alphabet : List Char :=
  "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".toList

def b64enc6 (n : Nat) : Char := (b64Alphabet[n % 64]?).getD 'A'

def b64EncBytes : List UInt8 → List Char
  | [] => []
  | [b0] =>
      let n := b0.toNat
      [b64enc6 (n >>> 2), b64enc6 ((n <<< 4) &&& 63), '=', '=']
  | [b0, b1] =>
      let n0 := b0.toNat; let n1 := b1.toNat
      [b64enc6 (n0 >>> 2), b64enc6 (((n0 <<< 4) ||| (n1 >>> 4)) &&& 63),
       b64enc6 ((n1 <<< 2) &&& 63), '=']
  | b0 :: b1 :: b2 :: rest =>
      let n0 := b0.toNat; let n1 := b1.toNat; let n2 := b2.toNat
      b64enc6 (n0 >>> 2) :: b64enc6 (((n0 <<< 4) ||| (n1 >>> 4)) &&& 63) ::
      b64enc6 (((n1 <<< 2) ||| (n2 >>> 6)) &&& 63) :: b64enc6 (n2 &&& 63) ::
      b64EncBytes rest

def b64val (c : Char) : Option Nat := List.idxOf? c b64Alphabet

def b64DecBytes : List Char → Option (List UInt8)
  | [] => some []
  | a :: b :: '=' :: '=' :: [] => do
      let na ← b64val a; let nb ← b64val b
      let n := (na <<< 2) ||| (nb >>> 4)
      pure [UInt8.ofNat (n &&& 255)]
  | a :: b :: c :: '=' :: [] => do
      let na ← b64val a; let nb ← b64val b; let nc ← b64val c
      let x := ((na <<< 2) ||| (nb >>> 4)) &&& 255
      let y := ((nb <<< 4) ||| (nc >>> 2)) &&& 255
      pure [UInt8.ofNat x, UInt8.ofNat y]
  | a :: b :: c :: d :: rest => do
      let na ← b64val a; let nb ← b64val b; let nc ← b64val c; let nd ← b64val d
      let x := ((na <<< 2) ||| (nb >>> 4)) &&& 255
      let y := ((nb <<< 4) ||| (nc >>> 2)) &&& 255
      let z := ((nc <<< 6) ||| nd) &&& 255
      let more ← b64DecBytes rest
      pure (UInt8.ofNat x :: UInt8.ofNat y :: UInt8.ofNat z :: more)
  | _ => none

def b64Encode (s : String) : List Char :=
  if s.isEmpty then [] else b64EncBytes s.toUTF8.toList

def b64Decode (cs : List Char) : Option String :=
  match cs with
  | [] => some ""
  | _ => (b64DecBytes cs).bind (fun bs => String.fromUTF8? ⟨bs.toArray⟩)

/-! ### comma helpers -/

def commaJoin (parts : List (List Char)) : List Char := joinSep ',' parts

def bracket (key : String) (inner : List Char) : List Char :=
  key.toList ++ ('[' :: inner) ++ [']']

/-! ### node field tags and the per-op field schema -/

inductive FTag | children | out | val | flf | pp | nn | den | nm | stage
  deriving DecidableEq, Repr

def opFields : String → List FTag
  | "num_exact"     => [.children, .out, .val, .nm]
  | "num_rounded"   => [.children, .out, .val, .flf, .nm]
  | "const_rounded" => [.children, .out, .val, .flf, .nm]
  | "var"           => [.children, .out, .nm]
  | "neg"           => [.children, .out]
  | "add"           => [.children, .out, .flf]
  | "sub"           => [.children, .out, .flf]
  | "mul"           => [.children, .out, .pp]
  | "div"           => [.children, .out, .pp, .den]
  | "powZero"       => [.children, .out, .nn, .nm]
  | "powEvenPos"    => [.children, .out, .flf, .nn, .nm]
  | "powOddPos"     => [.children, .out, .flf, .nn, .nm]
  | "powNegEven"    => [.children, .out, .flf, .pp, .nn, .den, .nm]
  | "powNegOdd"     => [.children, .out, .flf, .pp, .nn, .den, .nm]
  | "sin"           => [.children, .out]
  | "cos"           => [.children, .out]
  | "abs"           => [.children, .out]
  | "floor"         => [.children, .out]
  | "ceil"          => [.children, .out]
  | "round"         => [.children, .out]
  | "trunc"         => [.children, .out]
  | "min"           => [.children, .out]
  | "max"           => [.children, .out]
  | "sqrt"          => [.children, .out, .flf]
  | "exp"           => [.children, .out, .flf]
  | "ln"            => [.children, .out, .flf]
  | "atan"          => [.children, .out, .flf]
  | "asin"          => [.children, .out, .flf]
  | "acos"          => [.children, .out, .flf]
  | "hypot"         => [.children, .out, .flf]
  | "powGeneral"    => [.children, .out, .stage]
  | _               => []

/-- Emit the token(s) for one field tag of a node. -/
def emitTag (nd : Node) (tag : FTag) : List (List Char) :=
  match tag with
  | .children => [ bracket "children" (commaJoin (nd.children.map natDigits)) ]
  | .out      => [ bracket "out" (ratToStr nd.out_lo ++ ',' :: ratToStr nd.out_hi) ]
  | .val      => [ "val".toList, ratToStr nd.value ]
  | .flf      => [ bracket "f" (ratToStr nd.fl_lo ++ ',' :: ratToStr nd.fl_hi) ]
  | .pp       => [ bracket "p" (commaJoin [ratToStr nd.p1, ratToStr nd.p2, ratToStr nd.p3, ratToStr nd.p4]) ]
  | .nn       => [ "n".toList, natDigits nd.n ]
  | .den      => [ "den".toList, intToStr nd.den_sign ]
  | .nm       => [ "name".toList, nd.name.toList ]
  | .stage    => [ bracket "stage"
                    (commaJoin [ratToStr nd.Ll, ratToStr nd.Lu, ratToStr nd.Ml,
                                ratToStr nd.Mu, ratToStr nd.El, ratToStr nd.Eu]) ]

def emitNodeLine (nd : Node) : List Char :=
  joinSep ' '
    ([ "node".toList, natDigits nd.id, nd.op.toList ] ++ (opFields nd.op).flatMap (emitTag nd))

def emitHeaderLines (h : Header) : List (List Char) :=
  [ "jackal-eval-cert v".toList ++ natDigits h.schema_version,
    "model ".toList ++ h.model_const_version.toList,
    "exe ".toList ++ h.exe_identity.toList,
    "status ".toList ++ h.status_class.toList,
    "expr ".toList ++ h.expr_commitment.toList,
    "source ".toList ++ b64Encode h.source_commitment,
    "input ".toList ++ ratToStr h.input_lo ++ ' ' :: ratToStr h.input_hi,
    "root ".toList ++ natDigits h.root_id,
    "output ".toList ++ ratToStr h.output_lo ++ ' ' :: ratToStr h.output_hi ]

/-- All cert lines: header, one line per node (ascending), then `end`. -/
def emitCertLines (h : Header) (nodes : List Node) : List (List Char) :=
  emitHeaderLines h ++ nodes.map emitNodeLine ++ ["end".toList]

/-- Serialize to the canonical byte string (each line + LF; one trailing LF). -/
def emitCertL (h : Header) (nodes : List Node) : List Char :=
  (emitCertLines h nodes).flatMap (fun l => l ++ ['\n'])

def emitCert (h : Header) (nodes : List Node) : String :=
  String.ofList (emitCertL h nodes)

/-! ### parsing primitives -/

def stripPrefix : List Char → List Char → Option (List Char)
  | [], t => some t
  | _ :: _, [] => none
  | p :: ps, c :: cs => if p = c then stripPrefix ps cs else none

def stripBracket (key : String) (t : List Char) : Option (List Char) :=
  match stripPrefix (key.toList ++ ['[']) t with
  | none => none
  | some rest =>
      match rest.reverse with
      | ']' :: inner => some inner.reverse
      | _ => none

def parseBracketNats (key : String) (t : List Char) : Option (List Nat) :=
  (stripBracket key t).bind (fun inner =>
    if inner.isEmpty then some []
    else (splitOn ',' inner).mapM parseNatCanon)

def parseBracketRats2 (key : String) (t : List Char) : Option (ℚ × ℚ) :=
  (stripBracket key t).bind (fun inner =>
    match (splitOn ',' inner).mapM parseRatCanon with
    | some [a, b] => some (a, b)
    | _ => none)

def parseBracketRats4 (key : String) (t : List Char) : Option (ℚ × ℚ × ℚ × ℚ) :=
  (stripBracket key t).bind (fun inner =>
    match (splitOn ',' inner).mapM parseRatCanon with
    | some [a, b, c, d] => some (a, b, c, d)
    | _ => none)

def parseBracketRats6 (key : String) (t : List Char) : Option (ℚ × ℚ × ℚ × ℚ × ℚ × ℚ) :=
  (stripBracket key t).bind (fun inner =>
    match (splitOn ',' inner).mapM parseRatCanon with
    | some [a, b, c, d, e, f] => some (a, b, c, d, e, f)
    | _ => none)

/-! ### per-field consumption, schema-driven -/

def consumeTag (tag : FTag) (toks : List (List Char)) (nd : Node) :
    Except String (Node × List (List Char)) :=
  match tag with
  | .children => match toks with
      | t :: rest => match parseBracketNats "children" t with
          | some ids => .ok ({nd with children := ids}, rest)
          | none => .error "bad children field"
      | [] => .error "missing children field"
  | .out => match toks with
      | t :: rest => match parseBracketRats2 "out" t with
          | some (a, b) => .ok ({nd with out_lo := a, out_hi := b}, rest)
          | none => .error "bad out field"
      | [] => .error "missing out field"
  | .val => match toks with
      | key :: v :: rest =>
          if key = "val".toList then
            match parseRatCanon v with
            | some r => .ok ({nd with value := r}, rest)
            | none => .error "bad val field"
          else .error "expected val field"
      | _ => .error "missing val field"
  | .flf => match toks with
      | t :: rest => match parseBracketRats2 "f" t with
          | some (a, b) => .ok ({nd with fl_lo := a, fl_hi := b}, rest)
          | none => .error "bad f field"
      | [] => .error "missing f field"
  | .pp => match toks with
      | t :: rest => match parseBracketRats4 "p" t with
          | some (a, b, c, d) => .ok ({nd with p1 := a, p2 := b, p3 := c, p4 := d}, rest)
          | none => .error "bad p field"
      | [] => .error "missing p field"
  | .nn => match toks with
      | key :: v :: rest =>
          if key = "n".toList then
            match parseNatCanon v with
            | some k => .ok ({nd with n := k}, rest)
            | none => .error "bad n field"
          else .error "expected n field"
      | _ => .error "missing n field"
  | .den => match toks with
      | key :: v :: rest =>
          if key = "den".toList then
            match parseIntCanon v with
            | some s => .ok ({nd with den_sign := s}, rest)
            | none => .error "bad den field"
          else .error "expected den field"
      | _ => .error "missing den field"
  | .nm => match toks with
      | key :: v :: rest =>
          if key = "name".toList then .ok ({nd with name := String.ofList v}, rest)
          else .error "expected name field"
      | _ => .error "missing name field"
  | .stage => match toks with
      | t :: rest => match parseBracketRats6 "stage" t with
          | some (a, b, c, d, e, f) =>
              .ok ({nd with Ll := a, Lu := b, Ml := c, Mu := d, El := e, Eu := f}, rest)
          | none => .error "bad stage field"
      | [] => .error "missing stage field"

def parseFields : List FTag → List (List Char) → Node → Except String Node
  | [], [], nd => .ok nd
  | [], _ :: _, _ => .error "unexpected extra tokens on node line"
  | tag :: tags, toks, nd => do
      let (nd', toks') ← consumeTag tag toks nd
      parseFields tags toks' nd'

def baseNode (id : Nat) (op : String) : Node :=
  { id := id, op := op, children := [], out_lo := 0, out_hi := 0 }

def parseNodeLine (line : List Char) : Except String Node :=
  match splitOn ' ' line with
  | nodeTok :: idTok :: opTok :: fieldToks =>
      if nodeTok ≠ "node".toList then .error "node line must start with 'node'"
      else match parseNatCanon idTok with
        | none => .error "bad node id"
        | some id => parseFields (opFields (String.ofList opTok)) fieldToks (baseNode id (String.ofList opTok))
  | _ => .error "malformed node line"

/-! ### header line parsers -/

def parseMagicLine (line : List Char) : Except String Nat :=
  match stripPrefix "jackal-eval-cert v".toList line with
  | some rest => match parseNatCanon rest with
      | some v => .ok v
      | none => .error "bad schema version"
  | none => .error "expected magic line 'jackal-eval-cert v<n>'"

def parseStrKV (key : String) (line : List Char) : Except String String :=
  match stripPrefix (key.toList ++ [' ']) line with
  | some rest => .ok (String.ofList rest)
  | none => .error ("expected header key '" ++ key ++ "'")

def parseSourceLine (line : List Char) : Except String String :=
  match stripPrefix "source ".toList line with
  | some rest => match b64Decode rest with
      | some s => .ok s
      | none => .error "bad base64 source"
  | none => .error "expected header key 'source'"

def parseNatKV (key : String) (line : List Char) : Except String Nat :=
  match stripPrefix (key.toList ++ [' ']) line with
  | some rest => match parseNatCanon rest with
      | some n => .ok n
      | none => .error ("bad nat for header key '" ++ key ++ "'")
  | none => .error ("expected header key '" ++ key ++ "'")

def parseRatPairKV (key : String) (line : List Char) : Except String (ℚ × ℚ) :=
  match stripPrefix (key.toList ++ [' ']) line with
  | some rest => match (splitOn ' ' rest).mapM parseRatCanon with
      | some [a, b] => .ok (a, b)
      | _ => .error ("bad rat pair for header key '" ++ key ++ "'")
  | none => .error ("expected header key '" ++ key ++ "'")

/-! ### node list -/

def parseNodesUntilEnd : List (List Char) → List Node → Option Nat → Except String (List Node)
  | [], _, _ => .error "missing end marker"
  | line :: rest, acc, prev =>
      if line = "end".toList then
        match rest with
        | [] => .error "missing trailing newline after end"
        | [[]] => .ok acc.reverse
        | _ => .error "trailing bytes after end"
      else do
        let nd ← parseNodeLine line
        let _ ← (match prev with
                 | some p => if nd.id ≤ p then .error "node ids not strictly ascending" else .ok ()
                 | none => .ok ())
        let _ ← (if nd.children.all (fun c => decide (c < nd.id)) then .ok ()
                 else .error "forward or self child reference")
        parseNodesUntilEnd rest (nd :: acc) (some nd.id)

/-! ### the whole cert -/

def parseCertLines : List (List Char) → Except String (Header × List Node)
  | magic :: lmodel :: lexe :: lstatus :: lexpr :: lsource :: linput :: lroot :: loutput :: rest => do
      let sv ← parseMagicLine magic
      let model ← parseStrKV "model" lmodel
      let exeId ← parseStrKV "exe" lexe
      let status ← parseStrKV "status" lstatus
      let expr ← parseStrKV "expr" lexpr
      let source ← parseSourceLine lsource
      let (ilo, ihi) ← parseRatPairKV "input" linput
      let rid ← parseNatKV "root" lroot
      let (olo, ohi) ← parseRatPairKV "output" loutput
      let nodes ← parseNodesUntilEnd rest [] none
      .ok ({ schema_version := sv, model_const_version := model,
             expr_commitment := expr, source_commitment := source,
             input_lo := ilo, input_hi := ihi, root_id := rid,
             output_lo := olo, output_hi := ohi, exe_identity := exeId,
             status_class := status }, nodes)
  | _ => .error "truncated certificate: missing header lines"

def parseCert (s : String) : Except String (Header × List Node) :=
  parseCertLines (splitOn '\n' s.toList)

/-! ### Rejection battery (computable `decide` checks on concrete malformations)

`parseCert` is `List Char`/`Nat`/`String`-level and reduces in the kernel, so
each rejection is discharged by `decide` (NO `native_decide`).  `certRejected`
witnesses `∃ e, parseCert s = .error e`. -/

/-- `true` iff the parse produced an error. -/
def certRejected (r : Except String (Header × List Node)) : Bool :=
  match r with | .error _ => true | .ok _ => false

/-- A well-formed reference certificate string (accepted). -/
def refCert : String :=
  "jackal-eval-cert v1\nmodel jackal-iv-model-v1\nexe \nstatus bounded\nexpr (neg (var x))\nsource \ninput 2 5\nroot 1\noutput -5 -2\nnode 0 var children[] out[2,5] name x\nnode 1 neg children[0] out[-5,-2]\nend\n"

/-- REJECT: a non-canonical rational token `2/1` (must be written `2`). -/
def certNonCanonRat : String :=
  "jackal-eval-cert v1\nmodel jackal-iv-model-v1\nexe \nstatus bounded\nexpr (neg (var x))\nsource \ninput 2/1 5\nroot 1\noutput -5 -2\nnode 0 var children[] out[2,5] name x\nnode 1 neg children[0] out[-5,-2]\nend\n"

/-- REJECT: a duplicated header key (`model` where `exe` must appear). -/
def certDupHeaderKey : String :=
  "jackal-eval-cert v1\nmodel jackal-iv-model-v1\nmodel again\nstatus bounded\nexpr (neg (var x))\nsource \ninput 2 5\nroot 1\noutput -5 -2\nnode 0 var children[] out[2,5] name x\nnode 1 neg children[0] out[-5,-2]\nend\n"

/-- REJECT: bytes after the `end` line (trailing data). -/
def certTrailingBytes : String :=
  "jackal-eval-cert v1\nmodel jackal-iv-model-v1\nexe \nstatus bounded\nexpr (neg (var x))\nsource \ninput 2 5\nroot 1\noutput -5 -2\nnode 0 var children[] out[2,5] name x\nnode 1 neg children[0] out[-5,-2]\nend\nGARBAGE\n"

/-- REJECT: a duplicated node id (ids must be strictly ascending). -/
def certDupNodeId : String :=
  "jackal-eval-cert v1\nmodel jackal-iv-model-v1\nexe \nstatus bounded\nexpr (var x)\nsource \ninput 2 5\nroot 0\noutput 2 5\nnode 0 var children[] out[2,5] name x\nnode 0 var children[] out[2,5] name x\nend\n"

/-- REJECT: a forward/self child reference (child id ≥ parent id). -/
def certForwardChildRef : String :=
  "jackal-eval-cert v1\nmodel jackal-iv-model-v1\nexe \nstatus bounded\nexpr (neg (var x))\nsource \ninput 2 5\nroot 0\noutput 2 5\nnode 0 neg children[1] out[2,5]\nend\n"

set_option maxRecDepth 10000 in
theorem reject_nonCanonicalRat : certRejected (parseCert certNonCanonRat) = true := by decide

set_option maxRecDepth 10000 in
theorem reject_dupHeaderKey : certRejected (parseCert certDupHeaderKey) = true := by decide

set_option maxRecDepth 10000 in
theorem reject_trailingBytes : certRejected (parseCert certTrailingBytes) = true := by decide

set_option maxRecDepth 10000 in
theorem reject_dupNodeId : certRejected (parseCert certDupNodeId) = true := by decide

set_option maxRecDepth 10000 in
theorem reject_forwardChildRef : certRejected (parseCert certForwardChildRef) = true := by decide

-- The reference certificate is ACCEPTED (parses without error).
set_option maxRecDepth 10000 in
theorem accept_refCert : certRejected (parseCert refCert) = false := by decide


/-! ## Codec roundtrip: `parseCert (emitCert hdr nodes) = .ok (hdr, nodes)`

The canonical-string codec is invertible on the well-formed class `RoundtripWF`
(canonical nodes; ascending ids; below-parent child refs; empty `source_commitment`;
no raw newline in the opaque header/op/name strings).  Built bottom-up from the
general numeric-codec inverses (`parseNatCanon_natDigits` / `parseIntCanon_intToStr`
/ `parseRatCanon_ratToStr`), the splitter inverses, the schema-driven node-field
roundtrip, and the header/`end`/trailing-LF assembly.  Axiom-clean. -/

/-! ### splitter inverse lemmas -/

lemma splitOn_no_sep (sep : Char) : ∀ {t : List Char}, sep ∉ t → splitOn sep t = [t] := by
  intro t
  induction t with
  | nil => intro _; rfl
  | cons c cs ih =>
      intro h
      have hc : ¬ (c = sep) := fun e => h (by rw [e]; exact List.mem_cons_self)
      have hcs : sep ∉ cs := fun hx => h (List.mem_cons_of_mem c hx)
      simp only [splitOn, if_neg hc, ih hcs]

lemma splitOn_append_sep (sep : Char) : ∀ {t : List Char}, sep ∉ t →
    ∀ rest, splitOn sep (t ++ sep :: rest) = t :: splitOn sep rest := by
  intro t
  induction t with
  | nil => intro _ rest; simp [splitOn]
  | cons c cs ih =>
      intro h rest
      have hc : ¬ (c = sep) := fun e => h (by rw [e]; exact List.mem_cons_self)
      have hcs : sep ∉ cs := fun hx => h (List.mem_cons_of_mem c hx)
      simp only [List.cons_append, splitOn, if_neg hc, ih hcs rest]

lemma splitOn_flatMapLF : ∀ (ls : List (List Char)), (∀ l ∈ ls, '\n' ∉ l) →
    splitOn '\n' (ls.flatMap (fun l => l ++ ['\n'])) = ls ++ [[]] := by
  intro ls
  induction ls with
  | nil => intro _; rfl
  | cons l ls ih =>
      intro h
      have hl : '\n' ∉ l := h l List.mem_cons_self
      have hls : ∀ x ∈ ls, '\n' ∉ x := fun x hx => h x (List.mem_cons_of_mem l hx)
      simp only [List.flatMap_cons, List.append_assoc, List.cons_append, List.nil_append]
      rw [splitOn_append_sep '\n' hl, ih hls]

/-- Token-join inverse: joining nonempty separator-free tokens then splitting recovers them. -/
lemma splitOn_joinSep (sep : Char) : ∀ {ts : List (List Char)}, ts ≠ [] →
    (∀ t ∈ ts, sep ∉ t) → splitOn sep (joinSep sep ts) = ts := by
  intro ts
  induction ts with
  | nil => intro h _; exact absurd rfl h
  | cons t ts ih =>
      intro _ hmem
      have ht : sep ∉ t := hmem t List.mem_cons_self
      cases ts with
      | nil => simpa [joinSep] using splitOn_no_sep sep ht
      | cons t2 ts2 =>
          have hne : (t2 :: ts2) ≠ [] := by simp
          have htail : ∀ x ∈ (t2 :: ts2), sep ∉ x := fun x hx => hmem x (List.mem_cons_of_mem t hx)
          rw [show joinSep sep (t :: t2 :: ts2) = t ++ sep :: joinSep sep (t2 :: ts2) from rfl]
          rw [splitOn_append_sep sep ht, ih hne htail]

/-! ### emitted numeric tokens contain no separator chars -/

lemma natDigits_notMem {c : Char} (hc : digitCharVal c = none) (n : Nat) : c ∉ natDigits n := by
  intro hmem; exact natDigits_mem_digit n c hmem hc

lemma ratToStr_mem (q : ℚ) (c : Char) (h : c ∈ ratToStr q) :
    c = '-' ∨ c = '/' ∨ digitCharVal c ≠ none := by
  unfold ratToStr at h
  split at h
  · unfold intToStr at h
    split at h
    · rcases List.mem_cons.mp h with rfl | h
      · exact Or.inl rfl
      · exact Or.inr (Or.inr (natDigits_mem_digit _ _ h))
    · exact Or.inr (Or.inr (natDigits_mem_digit _ _ h))
  · rw [List.mem_append] at h
    rcases h with h | h
    · unfold intToStr at h; split at h
      · rcases List.mem_cons.mp h with rfl | h
        · exact Or.inl rfl
        · exact Or.inr (Or.inr (natDigits_mem_digit _ _ h))
      · exact Or.inr (Or.inr (natDigits_mem_digit _ _ h))
    · rcases List.mem_cons.mp h with rfl | h
      · exact Or.inr (Or.inl rfl)
      · exact Or.inr (Or.inr (natDigits_mem_digit _ _ h))

lemma ratToStr_notMem (q : ℚ) {c : Char}
    (h1 : c ≠ '-') (h2 : c ≠ '/') (h3 : digitCharVal c = none) : c ∉ ratToStr q := by
  intro hc; rcases ratToStr_mem q c hc with h | h | h
  · exact h1 h
  · exact h2 h
  · exact h h3

lemma ratToStr_no_nl (q : ℚ) : '\n' ∉ ratToStr q :=
  ratToStr_notMem q (by decide) (by decide) (by decide)
lemma ratToStr_no_sp (q : ℚ) : ' ' ∉ ratToStr q :=
  ratToStr_notMem q (by decide) (by decide) (by decide)
lemma ratToStr_no_comma (q : ℚ) : ',' ∉ ratToStr q :=
  ratToStr_notMem q (by decide) (by decide) (by decide)
lemma natDigits_no_nl (n : Nat) : '\n' ∉ natDigits n := natDigits_notMem (by decide) n
lemma natDigits_no_sp (n : Nat) : ' ' ∉ natDigits n := natDigits_notMem (by decide) n
lemma natDigits_no_comma (n : Nat) : ',' ∉ natDigits n := natDigits_notMem (by decide) n

/-! ### prefix / bracket parse inverses -/

lemma stripPrefix_append (p rest : List Char) : stripPrefix p (p ++ rest) = some rest := by
  induction p with
  | nil => rfl
  | cons c cs ih =>
      show (if c = c then stripPrefix cs (cs ++ rest) else none) = some rest
      rw [if_pos rfl, ih]

lemma stripBracket_bracket (key : String) (inner : List Char) :
    stripBracket key (bracket key inner) = some inner := by
  unfold stripBracket bracket
  rw [show key.toList ++ ('[' :: inner) ++ [']'] = (key.toList ++ ['[']) ++ (inner ++ [']']) by
        simp [List.append_assoc]]
  rw [stripPrefix_append]
  simp [List.reverse_append, List.reverse_reverse]

/-- Splitting a comma-join of separator-free tokens recovers the tokens (nonempty). -/
lemma splitOn_commaJoin {ts : List (List Char)} (hne : ts ≠ [])
    (h : ∀ t ∈ ts, ',' ∉ t) : splitOn ',' (commaJoin ts) = ts :=
  splitOn_joinSep ',' hne h

lemma joinSep_cons_ne_nil (sep : Char) (t : List Char) (ts : List (List Char))
    (ht : t ≠ []) : joinSep sep (t :: ts) ≠ [] := by
  cases ts with
  | nil => simpa [joinSep] using ht
  | cons t2 ts2 =>
      rw [show joinSep sep (t :: t2 :: ts2) = t ++ sep :: joinSep sep (t2 :: ts2) from rfl]
      cases t with
      | nil => exact absurd rfl ht
      | cons c cs => simp

lemma mapM_map_natDigits (ids : List Nat) :
    (ids.map natDigits).mapM parseNatCanon = some ids := by
  induction ids with
  | nil => rfl
  | cons a as ih =>
      simp only [List.map_cons, List.mapM_cons, parseNatCanon_natDigits, ih]
      rfl

lemma mapM_ratToStr₂ (a b : ℚ) :
    ([ratToStr a, ratToStr b]).mapM parseRatCanon = some [a, b] := by
  simp only [List.mapM_cons, List.mapM_nil, parseRatCanon_ratToStr]
  rfl

lemma mapM_ratToStr₄ (a b c d : ℚ) :
    ([ratToStr a, ratToStr b, ratToStr c, ratToStr d]).mapM parseRatCanon = some [a, b, c, d] := by
  simp only [List.mapM_cons, List.mapM_nil, parseRatCanon_ratToStr]
  rfl

lemma mapM_ratToStr₆ (a b c d e f : ℚ) :
    ([ratToStr a, ratToStr b, ratToStr c, ratToStr d, ratToStr e, ratToStr f]).mapM parseRatCanon
      = some [a, b, c, d, e, f] := by
  simp only [List.mapM_cons, List.mapM_nil, parseRatCanon_ratToStr]
  rfl

lemma parseBracketRats2_emit (key : String) (a b : ℚ) :
    parseBracketRats2 key (bracket key (ratToStr a ++ ',' :: ratToStr b)) = some (a, b) := by
  unfold parseBracketRats2
  rw [stripBracket_bracket]
  simp only [Option.bind_some]
  rw [splitOn_append_sep ',' (ratToStr_no_comma a), splitOn_no_sep ',' (ratToStr_no_comma b),
      mapM_ratToStr₂]

lemma parseBracketRats4_emit (key : String) (a b c d : ℚ) :
    parseBracketRats4 key (bracket key (commaJoin [ratToStr a, ratToStr b, ratToStr c, ratToStr d]))
      = some (a, b, c, d) := by
  unfold parseBracketRats4
  rw [stripBracket_bracket]
  simp only [Option.bind_some]
  rw [splitOn_commaJoin (by simp) (by
        intro t ht; fin_cases ht <;> exact ratToStr_no_comma _), mapM_ratToStr₄]

lemma parseBracketRats6_emit (key : String) (a b c d e f : ℚ) :
    parseBracketRats6 key
        (bracket key (commaJoin [ratToStr a, ratToStr b, ratToStr c, ratToStr d, ratToStr e, ratToStr f]))
      = some (a, b, c, d, e, f) := by
  unfold parseBracketRats6
  rw [stripBracket_bracket]
  simp only [Option.bind_some]
  rw [splitOn_commaJoin (by simp) (by
        intro t ht; fin_cases ht <;> exact ratToStr_no_comma _), mapM_ratToStr₆]

lemma parseBracketNats_emit (key : String) (ids : List Nat) :
    parseBracketNats key (bracket key (commaJoin (ids.map natDigits))) = some ids := by
  unfold parseBracketNats
  rw [stripBracket_bracket]
  simp only [Option.bind_some]
  cases ids with
  | nil => rfl
  | cons a as =>
      have hLne : ((a :: as).map natDigits) ≠ [] := by simp
      have hnc : ∀ t ∈ ((a :: as).map natDigits), ',' ∉ t := by
        intro t ht; rw [List.mem_map] at ht; obtain ⟨k, _, rfl⟩ := ht; exact natDigits_no_comma k
      have hCJne : commaJoin ((a :: as).map natDigits) ≠ [] := by
        rw [List.map_cons]
        exact joinSep_cons_ne_nil ',' _ _ (natDigits_ne_nil a)
      have hEmpty : (commaJoin ((a :: as).map natDigits)).isEmpty = false := by
        cases h : commaJoin ((a :: as).map natDigits) with
        | nil => exact absurd h hCJne
        | cons => rfl
      rw [hEmpty]
      simp only [Bool.false_eq_true, if_false]
      rw [splitOn_commaJoin hLne hnc, mapM_map_natDigits]

/-! ### no-separator membership infrastructure -/

lemma joinSep_notMem (sep c : Char) (hc : c ≠ sep) :
    ∀ {ts : List (List Char)}, (∀ t ∈ ts, c ∉ t) → c ∉ joinSep sep ts := by
  intro ts
  induction ts with
  | nil => intro _ hmem; simp [joinSep] at hmem
  | cons t ts ih =>
      intro h hmem
      have ht : c ∉ t := h t List.mem_cons_self
      cases ts with
      | nil => rw [show joinSep sep [t] = t from rfl] at hmem; exact ht hmem
      | cons t2 ts2 =>
          rw [show joinSep sep (t :: t2 :: ts2) = t ++ sep :: joinSep sep (t2 :: ts2) from rfl,
              List.mem_append, List.mem_cons] at hmem
          rcases hmem with h1 | h1 | h1
          · exact ht h1
          · exact hc h1
          · exact ih (fun x hx => h x (List.mem_cons_of_mem t hx)) h1

lemma commaJoin_notMem (c : Char) (hc : c ≠ ',') {ts : List (List Char)}
    (h : ∀ t ∈ ts, c ∉ t) : c ∉ commaJoin ts := joinSep_notMem ',' c hc h

lemma bracket_notMem (key : String) (c : Char) (inner : List Char)
    (hkey : c ∉ key.toList) (hlb : c ≠ '[') (hrb : c ≠ ']') (hin : c ∉ inner) :
    c ∉ bracket key inner := by
  unfold bracket
  intro hmem
  rw [List.mem_append, List.mem_append, List.mem_cons, List.mem_singleton] at hmem
  rcases hmem with (h | h | h) | h
  · exact hkey h
  · exact hlb h
  · exact hin h
  · exact hrb h

lemma intToStr_mem (i : Int) (c : Char) (h : c ∈ intToStr i) :
    c = '-' ∨ digitCharVal c ≠ none := by
  unfold intToStr at h; split at h
  · rcases List.mem_cons.mp h with rfl | h
    · exact Or.inl rfl
    · exact Or.inr (natDigits_mem_digit _ _ h)
  · exact Or.inr (natDigits_mem_digit _ _ h)

lemma intToStr_notMem (i : Int) {c : Char} (h1 : c ≠ '-') (h3 : digitCharVal c = none) :
    c ∉ intToStr i := by
  intro hc; rcases intToStr_mem i c hc with h | h
  · exact h1 h
  · exact h h3

lemma intToStr_no_sp (i : Int) : ' ' ∉ intToStr i := intToStr_notMem i (by decide) (by decide)
lemma intToStr_no_nl (i : Int) : '\n' ∉ intToStr i := intToStr_notMem i (by decide) (by decide)

/-- Every token the schema emits for a node avoids char `c`, given `c` avoids the
name, the digits, and the fixed structural/key chars. -/
lemma emitTag_notMem (nd : Node) (c : Char)
    (hname : c ∉ nd.name.toList) (hd : digitCharVal c = none)
    (hlb : c ≠ '[') (hrb : c ≠ ']') (hcm : c ≠ ',') (hng : c ≠ '-') (hsl : c ≠ '/')
    (hk1 : c ∉ "children".toList) (hk2 : c ∉ "out".toList) (hk3 : c ∉ "val".toList)
    (hk4 : c ∉ "f".toList) (hk5 : c ∉ "p".toList) (hk6 : c ∉ "n".toList)
    (hk7 : c ∉ "den".toList) (hk8 : c ∉ "name".toList) (hk9 : c ∉ "stage".toList) :
    ∀ tag, ∀ t ∈ emitTag nd tag, c ∉ t := by
  have hrat : ∀ q : ℚ, c ∉ ratToStr q := fun q => ratToStr_notMem q hng hsl hd
  have hnat : ∀ n : Nat, c ∉ natDigits n := fun n => natDigits_notMem hd n
  have hint : ∀ i : Int, c ∉ intToStr i := fun i => intToStr_notMem i hng hd
  have hpair : ∀ (a b : ℚ), c ∉ (ratToStr a ++ ',' :: ratToStr b) := by
    intro a b hmem
    rw [List.mem_append, List.mem_cons] at hmem
    rcases hmem with h | h | h
    · exact hrat _ h
    · exact hcm h
    · exact hrat _ h
  intro tag t ht
  cases tag <;> simp only [emitTag, List.mem_cons, List.not_mem_nil, or_false] at ht
  · -- children
    subst ht
    refine bracket_notMem _ c _ hk1 hlb hrb (commaJoin_notMem c hcm ?_)
    intro s hs; rw [List.mem_map] at hs; obtain ⟨k, _, rfl⟩ := hs; exact hnat k
  · -- out
    subst ht; exact bracket_notMem _ c _ hk2 hlb hrb (hpair _ _)
  · -- val
    rcases ht with rfl | rfl
    · exact hk3
    · exact hrat _
  · -- flf
    subst ht; exact bracket_notMem _ c _ hk4 hlb hrb (hpair _ _)
  · -- pp
    subst ht
    refine bracket_notMem _ c _ hk5 hlb hrb (commaJoin_notMem c hcm ?_)
    intro s hs; fin_cases hs <;> exact hrat _
  · -- nn
    rcases ht with rfl | rfl
    · exact hk6
    · exact hnat _
  · -- den
    rcases ht with rfl | rfl
    · exact hk7
    · exact hint _
  · -- nm
    rcases ht with rfl | rfl
    · exact hk8
    · exact hname
  · -- stage
    subst ht
    refine bracket_notMem _ c _ hk9 hlb hrb (commaJoin_notMem c hcm ?_)
    intro s hs; fin_cases hs <;> exact hrat _

lemma emitTag_no_sp (nd : Node) (hname : ' ' ∉ nd.name.toList) :
    ∀ tag, ∀ t ∈ emitTag nd tag, ' ' ∉ t :=
  emitTag_notMem nd ' ' hname (by decide) (by decide) (by decide) (by decide) (by decide)
    (by decide) (by decide) (by decide) (by decide) (by decide) (by decide) (by decide)
    (by decide) (by decide) (by decide)

lemma emitTag_no_nl (nd : Node) (hname : '\n' ∉ nd.name.toList) :
    ∀ tag, ∀ t ∈ emitTag nd tag, '\n' ∉ t :=
  emitTag_notMem nd '\n' hname (by decide) (by decide) (by decide) (by decide) (by decide)
    (by decide) (by decide) (by decide) (by decide) (by decide) (by decide) (by decide)
    (by decide) (by decide) (by decide)

/-! ### node field roundtrip -/

/-- The field a single tag writes back onto the accumulator, taking values from `nd`. -/
def setTag (nd acc : Node) : FTag → Node
  | .children => {acc with children := nd.children}
  | .out      => {acc with out_lo := nd.out_lo, out_hi := nd.out_hi}
  | .val      => {acc with value := nd.value}
  | .flf      => {acc with fl_lo := nd.fl_lo, fl_hi := nd.fl_hi}
  | .pp       => {acc with p1 := nd.p1, p2 := nd.p2, p3 := nd.p3, p4 := nd.p4}
  | .nn       => {acc with n := nd.n}
  | .den      => {acc with den_sign := nd.den_sign}
  | .nm       => {acc with name := nd.name}
  | .stage    => {acc with Ll := nd.Ll, Lu := nd.Lu, Ml := nd.Ml, Mu := nd.Mu, El := nd.El, Eu := nd.Eu}

def setTags (nd : Node) : Node → List FTag → Node
  | acc, []          => acc
  | acc, tag :: tags => setTags nd (setTag nd acc tag) tags

/-- Parsing exactly the tokens the schema emits recovers each field. -/
lemma consumeTag_emit (nd acc : Node) (tag : FTag) (more : List (List Char)) :
    consumeTag tag (emitTag nd tag ++ more) acc = .ok (setTag nd acc tag, more) := by
  cases tag <;>
    simp only [emitTag, setTag, consumeTag, List.cons_append, List.nil_append,
      parseBracketNats_emit, parseBracketRats2_emit, parseBracketRats4_emit,
      parseBracketRats6_emit, parseRatCanon_ratToStr, parseNatCanon_natDigits,
      parseIntCanon_intToStr, String.ofList_toList, ↓reduceIte]

lemma parseFields_emit (nd : Node) :
    ∀ (tags : List FTag) (acc : Node),
      parseFields tags (tags.flatMap (emitTag nd)) acc = .ok (setTags nd acc tags) := by
  intro tags
  induction tags with
  | nil => intro acc; rfl
  | cons tag tags ih =>
      intro acc
      rw [List.flatMap_cons]
      show (consumeTag tag (emitTag nd tag ++ tags.flatMap (emitTag nd)) acc >>=
              fun x => parseFields tags x.2 x.1) = .ok (setTags nd acc (tag :: tags))
      rw [consumeTag_emit nd acc tag (tags.flatMap (emitTag nd))]
      show parseFields tags (tags.flatMap (emitTag nd)) (setTag nd acc tag)
            = .ok (setTags nd acc (tag :: tags))
      rw [ih (setTag nd acc tag), setTags]

/-- The node recovered by parsing: op-relevant fields from `nd`, the rest at defaults. -/
def canonicalNode (nd : Node) : Node := setTags nd (baseNode nd.id nd.op) (opFields nd.op)

lemma parseNodeLine_emit (nd : Node)
    (hopSp : ' ' ∉ nd.op.toList) (hnameSp : ' ' ∉ nd.name.toList) :
    parseNodeLine (emitNodeLine nd) = .ok (canonicalNode nd) := by
  have htf : ∀ t ∈ (["node".toList, natDigits nd.id, nd.op.toList]
      ++ (opFields nd.op).flatMap (emitTag nd)), ' ' ∉ t := by
    intro t ht
    rw [List.mem_append] at ht
    rcases ht with ht | ht
    · fin_cases ht
      · decide
      · exact natDigits_no_sp _
      · exact hopSp
    · rw [List.mem_flatMap] at ht
      obtain ⟨tag, _, hmem⟩ := ht
      exact emitTag_no_sp nd hnameSp tag t hmem
  unfold parseNodeLine emitNodeLine
  rw [splitOn_joinSep ' ' (by simp) htf]
  simp only [List.cons_append, List.nil_append, ne_eq, not_true_eq_false, if_false,
    parseNatCanon_natDigits, String.ofList_toList, parseFields_emit, canonicalNode]



/-! ### header line inverses -/

lemma parseMagicLine_emit (n : Nat) :
    parseMagicLine ("jackal-eval-cert v".toList ++ natDigits n) = .ok n := by
  simp only [parseMagicLine, stripPrefix_append, parseNatCanon_natDigits]

lemma parseStrKV_emit (key : String) (pre : List Char) (v : String)
    (h : key.toList ++ [' '] = pre) : parseStrKV key (pre ++ v.toList) = .ok v := by
  subst h; simp only [parseStrKV, stripPrefix_append, String.ofList_toList]

lemma parseNatKV_emit (key : String) (pre : List Char) (n : Nat)
    (h : key.toList ++ [' '] = pre) : parseNatKV key (pre ++ natDigits n) = .ok n := by
  subst h; simp only [parseNatKV, stripPrefix_append, parseNatCanon_natDigits]

lemma parseRatPairKV_emit (key : String) (pre : List Char) (a b : ℚ)
    (h : key.toList ++ [' '] = pre) :
    parseRatPairKV key (pre ++ (ratToStr a ++ ' ' :: ratToStr b)) = .ok (a, b) := by
  subst h
  simp only [parseRatPairKV, stripPrefix_append]
  rw [splitOn_append_sep ' ' (ratToStr_no_sp a), splitOn_no_sep ' ' (ratToStr_no_sp b),
      mapM_ratToStr₂]

lemma parseSourceLine_emit_empty :
    parseSourceLine ("source ".toList ++ b64Encode "") = .ok "" := by
  have h1 : b64Encode "" = [] := by decide
  rw [h1]
  unfold parseSourceLine
  rw [stripPrefix_append]
  rfl

/-! ### node-list inverse -/

lemma emitNodeLine_head (nd : Node) :
    (emitNodeLine nd).head? = some 'n' := by
  unfold emitNodeLine
  simp only [List.cons_append, List.nil_append]
  rw [show joinSep ' ' ("node".toList :: natDigits nd.id :: nd.op.toList
        :: (opFields nd.op).flatMap (emitTag nd))
        = "node".toList ++ ' ' :: joinSep ' ' (natDigits nd.id :: nd.op.toList
            :: (opFields nd.op).flatMap (emitTag nd)) from rfl]
  rfl

lemma emitNodeLine_ne_end (nd : Node) : emitNodeLine nd ≠ "end".toList := by
  intro h
  have := emitNodeLine_head nd
  rw [h] at this
  simp at this

def NodesAsc : Option Nat → List Node → Prop
  | _,    []        => True
  | prev, nd :: nds =>
      (match prev with | some p => p < nd.id | none => True)
        ∧ (∀ c ∈ nd.children, c < nd.id) ∧ NodesAsc (some nd.id) nds

lemma parseNodes_step (nd : Node) (rest : List (List Char)) (acc : List Node) (prev : Option Nat)
    (hcanon : canonicalNode nd = nd) (hopSp : ' ' ∉ nd.op.toList) (hnameSp : ' ' ∉ nd.name.toList)
    (hprev : match prev with | some p => p < nd.id | none => True)
    (hchild : ∀ c ∈ nd.children, c < nd.id) :
    parseNodesUntilEnd (emitNodeLine nd :: rest) acc prev
      = parseNodesUntilEnd rest (nd :: acc) (some nd.id) := by
  have hg2 : (nd.children.all (fun c => decide (c < nd.id))) = true := by
    rw [List.all_eq_true]; intro c hc; simp only [decide_eq_true_eq]; exact hchild c hc
  simp only [parseNodesUntilEnd, if_neg (emitNodeLine_ne_end nd),
    parseNodeLine_emit nd hopSp hnameSp, hcanon, bind, Except.bind]
  cases prev with
  | none => simp only [hg2, if_true]
  | some p =>
      have hlt : ¬ nd.id ≤ p := by simp only [] at hprev; omega
      simp only [if_neg hlt, hg2, if_true]

lemma parseNodesUntilEnd_emit :
    ∀ (nodes : List Node) (acc : List Node) (prev : Option Nat),
      (∀ nd ∈ nodes, canonicalNode nd = nd ∧ ' ' ∉ nd.op.toList ∧ ' ' ∉ nd.name.toList) →
      NodesAsc prev nodes →
      parseNodesUntilEnd (nodes.map emitNodeLine ++ ["end".toList, []]) acc prev
        = .ok (acc.reverse ++ nodes) := by
  intro nodes
  induction nodes with
  | nil =>
      intro acc prev _ _
      simp only [List.map_nil, List.nil_append]
      unfold parseNodesUntilEnd
      rw [if_pos rfl]
      simp
  | cons nd nds ih =>
      intro acc prev hwf hasc
      obtain ⟨hcanon, hopSp, hnameSp⟩ := hwf nd List.mem_cons_self
      obtain ⟨hprev, hchild, hasc'⟩ := hasc
      simp only [List.map_cons, List.cons_append]
      rw [parseNodes_step nd _ acc prev hcanon hopSp hnameSp hprev hchild]
      rw [ih (nd :: acc) (some nd.id) (fun x hx => hwf x (List.mem_cons_of_mem nd hx)) hasc']
      simp

/-! ### line no-newline facts and the assembly -/

lemma notMem_append {c : Char} {a b : List Char} (ha : c ∉ a) (hb : c ∉ b) : c ∉ a ++ b := by
  rw [List.mem_append]
  rintro (h | h)
  · exact ha h
  · exact hb h

lemma notMem_cons {c d : Char} {b : List Char} (hd : c ≠ d) (hb : c ∉ b) : c ∉ d :: b := by
  rw [List.mem_cons]
  rintro (h | h)
  · exact hd h
  · exact hb h

lemma emitNodeLine_no_nl (nd : Node) (hop : '\n' ∉ nd.op.toList) (hname : '\n' ∉ nd.name.toList) :
    '\n' ∉ emitNodeLine nd := by
  unfold emitNodeLine
  refine joinSep_notMem ' ' '\n' (by decide) ?_
  intro t ht
  rw [List.mem_append] at ht
  rcases ht with ht | ht
  · fin_cases ht
    · decide
    · exact natDigits_no_nl _
    · exact hop
  · rw [List.mem_flatMap] at ht
    obtain ⟨tag, _, hmem⟩ := ht
    exact emitTag_no_nl nd hname tag t hmem

structure RoundtripWF (hdr : Header) (nodes : List Node) : Prop where
  source_empty : hdr.source_commitment = ""
  model_nl : '\n' ∉ hdr.model_const_version.toList
  exe_nl : '\n' ∉ hdr.exe_identity.toList
  status_nl : '\n' ∉ hdr.status_class.toList
  expr_nl : '\n' ∉ hdr.expr_commitment.toList
  nodes_wf : ∀ nd ∈ nodes, canonicalNode nd = nd ∧ ' ' ∉ nd.op.toList ∧ ' ' ∉ nd.name.toList
              ∧ '\n' ∉ nd.op.toList ∧ '\n' ∉ nd.name.toList
  nodes_asc : NodesAsc none nodes

lemma emitCertLines_no_nl (hdr : Header) (nodes : List Node) (wf : RoundtripWF hdr nodes) :
    ∀ l ∈ emitCertLines hdr nodes, '\n' ∉ l := by
  intro l hl
  unfold emitCertLines emitHeaderLines at hl
  rw [List.mem_append, List.mem_append] at hl
  rcases hl with (hl | hl) | hl
  · -- header lines (9)
    fin_cases hl
    · exact notMem_append (by decide) (natDigits_no_nl _)
    · exact notMem_append (by decide) wf.model_nl
    · exact notMem_append (by decide) wf.exe_nl
    · exact notMem_append (by decide) wf.status_nl
    · exact notMem_append (by decide) wf.expr_nl
    · rw [wf.source_empty, show b64Encode "" = [] from by decide, List.append_nil]; decide
    · exact notMem_append (notMem_append (by decide) (ratToStr_no_nl _)) (notMem_cons (by decide) (ratToStr_no_nl _))
    · exact notMem_append (by decide) (natDigits_no_nl _)
    · exact notMem_append (notMem_append (by decide) (ratToStr_no_nl _)) (notMem_cons (by decide) (ratToStr_no_nl _))
  · -- node lines
    rw [List.mem_map] at hl
    obtain ⟨nd, hnd, rfl⟩ := hl
    obtain ⟨_, _, _, hop, hname⟩ := wf.nodes_wf nd hnd
    exact emitNodeLine_no_nl nd hop hname
  · -- "end"
    simp only [List.mem_singleton] at hl; subst hl; decide

/-- ROUNDTRIP: for a well-formed cert, `parseCert (emitCert hdr nodes) = .ok (hdr, nodes)`. -/
theorem parse_emit_roundtrip (hdr : Header) (nodes : List Node) (wf : RoundtripWF hdr nodes) :
    parseCert (emitCert hdr nodes) = .ok (hdr, nodes) := by
  unfold parseCert emitCert
  rw [String.toList_ofList]
  unfold emitCertL
  rw [splitOn_flatMapLF _ (emitCertLines_no_nl hdr nodes wf)]
  unfold emitCertLines emitHeaderLines
  simp only [List.cons_append, List.nil_append, List.append_assoc]
  unfold parseCertLines
  dsimp only
  rw [wf.source_empty,
      parseMagicLine_emit hdr.schema_version,
      parseStrKV_emit "model" "model ".toList hdr.model_const_version (by decide),
      parseStrKV_emit "exe" "exe ".toList hdr.exe_identity (by decide),
      parseStrKV_emit "status" "status ".toList hdr.status_class (by decide),
      parseStrKV_emit "expr" "expr ".toList hdr.expr_commitment (by decide),
      parseSourceLine_emit_empty,
      parseRatPairKV_emit "input" "input ".toList hdr.input_lo hdr.input_hi (by decide),
      parseNatKV_emit "root" "root ".toList hdr.root_id (by decide),
      parseRatPairKV_emit "output" "output ".toList hdr.output_lo hdr.output_hi (by decide),
      parseNodesUntilEnd_emit nodes [] none
        (fun nd hnd => ⟨(wf.nodes_wf nd hnd).1, (wf.nodes_wf nd hnd).2.1, (wf.nodes_wf nd hnd).2.2.1⟩)
        wf.nodes_asc]
  simp only [List.reverse_nil, List.nil_append, bind, Except.bind]
  rw [← wf.source_empty]

end JackalIv.Cert
