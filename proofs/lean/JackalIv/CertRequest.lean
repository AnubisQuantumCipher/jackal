/-
JackalIv/CertRequest.lean — exact request binding for `jackal_cert_check`.

The certificate checker deliberately treats the evaluator as untrusted.  This
module closes the remaining request-relabel boundary inside Lean itself:

* the operation must be exactly `range-bound-cert`;
* the raw expression is parsed by `Parser.parseRaw`, the computable exact-ℚ
  parser whose embedding definitionally supplies `Parser.parse`;
* the parser tree is lowered by the computable mirror of `Lower.lower` and is
  compared structurally, including every numeric token's exact rational value,
  with the expression reconstructed from the certificate nodes;
* both CLI limits are parsed by the canonical rational codec and must equal the
  certificate header's input interval; and
* every certificate node must belong to the exact FORMAL release allowlist,
  excluding checker-sound but policy-unreleased negative/general powers and
  TCB-backed transcendental nodes; and
* release mode requires the header status `bounded`.

`request_bound_certified_release` composes that exact match with the existing
`cert_check_sound`/`parse_lower_encloses` chain.  No unrestricted-expression
claim is introduced: an unparsed, unlowerable, or unmatched request refuses.
-/
import JackalIv.CertCodec
import JackalIv.CertSound
import JackalIv.Correspondence

namespace JackalIv.Cert

open JackalIv
open JackalIv.Parser

/-- The only operation admitted by the general range-certificate release
checker.  Other checker modes are diagnostic and never produce release ACCEPT. -/
def rangeBoundCommand : String := "range-bound-cert"

/-! ### Computable lowering of the exact parser tree -/

def rawNumVal? : RawExpr → Option ℚ
  | RawExpr.num q _ => some q
  | _ => none

def rawLowerNeg : RawExpr → RawExpr
  | RawExpr.neg w => w
  | u => RawExpr.neg u

def rawLowerAdd (l r : RawExpr) : RawExpr :=
  if rawNumVal? l = some 0 then r
  else if rawNumVal? r = some 0 then l
  else RawExpr.add l r

def rawLowerSub (l r : RawExpr) : RawExpr :=
  if rawNumVal? r = some 0 then l
  else if rawNumVal? l = some 0 then rawLowerNeg r
  else RawExpr.sub l r

def rawLowerMul (l r : RawExpr) : RawExpr :=
  if rawNumVal? l = some 1 then r
  else if rawNumVal? r = some 1 then l
  else RawExpr.mul l r

def rawLowerDiv (l r : RawExpr) : Option RawExpr :=
  if rawNumVal? r = some 0 then none
  else if rawNumVal? r = some 1 then some l
  else some (RawExpr.div l r)

def rawLowerMod (l r : RawExpr) : Option RawExpr :=
  if rawNumVal? r = some 0 then none else some (RawExpr.mod l r)

def rawLowerPow (b e : RawExpr) : RawExpr :=
  if rawNumVal? e = some 1 then b else RawExpr.pow b e

/-- Exact-ℚ counterpart of `Lower.lower`; fully executable. -/
def lowerRaw : RawExpr → Option RawExpr
  | RawExpr.num q t => some (RawExpr.num q t)
  | RawExpr.var n => some (RawExpr.var n)
  | RawExpr.constant n => some (RawExpr.constant n)
  | RawExpr.neg u => (lowerRaw u).map rawLowerNeg
  | RawExpr.add l r => do rawLowerAdd (← lowerRaw l) (← lowerRaw r)
  | RawExpr.sub l r => do rawLowerSub (← lowerRaw l) (← lowerRaw r)
  | RawExpr.mul l r => do rawLowerMul (← lowerRaw l) (← lowerRaw r)
  | RawExpr.div l r => do rawLowerDiv (← lowerRaw l) (← lowerRaw r)
  | RawExpr.mod l r => do rawLowerMod (← lowerRaw l) (← lowerRaw r)
  | RawExpr.pow b e => do rawLowerPow (← lowerRaw b) (← lowerRaw e)
  | RawExpr.call1 n u => (lowerRaw u).map (RawExpr.call1 n ·)
  | RawExpr.call2 n u v => do return RawExpr.call2 n (← lowerRaw u) (← lowerRaw v)

lemma rawNumVal_zero_iff (e : RawExpr) :
    rawNumVal? e = some 0 ↔ numVal? e.toExpr = some 0 := by
  cases e <;> simp [rawNumVal?, RawExpr.toExpr, numVal?]

lemma rawNumVal_one_iff (e : RawExpr) :
    rawNumVal? e = some 1 ↔ numVal? e.toExpr = some 1 := by
  cases e <;> simp [rawNumVal?, RawExpr.toExpr, numVal?]
  norm_cast

lemma rawLowerNeg_toExpr (e : RawExpr) :
    (rawLowerNeg e).toExpr = lowerNeg e.toExpr := by
  cases e <;> rfl

lemma rawLowerAdd_toExpr (l r : RawExpr) :
    (rawLowerAdd l r).toExpr = lowerAdd l.toExpr r.toExpr := by
  unfold rawLowerAdd lowerAdd
  by_cases hl : rawNumVal? l = some 0
  · rw [if_pos hl, if_pos ((rawNumVal_zero_iff l).mp hl)]
  · rw [if_neg hl, if_neg (mt (rawNumVal_zero_iff l).mpr hl)]
    by_cases hr : rawNumVal? r = some 0
    · rw [if_pos hr, if_pos ((rawNumVal_zero_iff r).mp hr)]
    · rw [if_neg hr, if_neg (mt (rawNumVal_zero_iff r).mpr hr)]
      rfl

lemma rawLowerSub_toExpr (l r : RawExpr) :
    (rawLowerSub l r).toExpr = lowerSub l.toExpr r.toExpr := by
  unfold rawLowerSub lowerSub
  by_cases hr : rawNumVal? r = some 0
  · rw [if_pos hr, if_pos ((rawNumVal_zero_iff r).mp hr)]
  · rw [if_neg hr, if_neg (mt (rawNumVal_zero_iff r).mpr hr)]
    by_cases hl : rawNumVal? l = some 0
    · rw [if_pos hl, if_pos ((rawNumVal_zero_iff l).mp hl), rawLowerNeg_toExpr]
    · rw [if_neg hl, if_neg (mt (rawNumVal_zero_iff l).mpr hl)]
      rfl

lemma rawLowerMul_toExpr (l r : RawExpr) :
    (rawLowerMul l r).toExpr = lowerMul l.toExpr r.toExpr := by
  unfold rawLowerMul lowerMul
  by_cases hl : rawNumVal? l = some 1
  · rw [if_pos hl, if_pos ((rawNumVal_one_iff l).mp hl)]
  · rw [if_neg hl, if_neg (mt (rawNumVal_one_iff l).mpr hl)]
    by_cases hr : rawNumVal? r = some 1
    · rw [if_pos hr, if_pos ((rawNumVal_one_iff r).mp hr)]
    · rw [if_neg hr, if_neg (mt (rawNumVal_one_iff r).mpr hr)]
      rfl

lemma rawLowerDiv_toExpr (l r : RawExpr) :
    (rawLowerDiv l r).map RawExpr.toExpr = lowerDiv l.toExpr r.toExpr := by
  unfold rawLowerDiv lowerDiv
  by_cases hz : rawNumVal? r = some 0
  · rw [if_pos hz, if_pos ((rawNumVal_zero_iff r).mp hz)]; rfl
  · rw [if_neg hz, if_neg (mt (rawNumVal_zero_iff r).mpr hz)]
    by_cases ho : rawNumVal? r = some 1
    · rw [if_pos ho, if_pos ((rawNumVal_one_iff r).mp ho)]; rfl
    · rw [if_neg ho, if_neg (mt (rawNumVal_one_iff r).mpr ho)]; rfl

lemma rawLowerMod_toExpr (l r : RawExpr) :
    (rawLowerMod l r).map RawExpr.toExpr = lowerMod l.toExpr r.toExpr := by
  unfold rawLowerMod lowerMod
  by_cases hz : rawNumVal? r = some 0
  · rw [if_pos hz, if_pos ((rawNumVal_zero_iff r).mp hz)]; rfl
  · rw [if_neg hz, if_neg (mt (rawNumVal_zero_iff r).mpr hz)]; rfl

lemma rawLowerPow_toExpr (b e : RawExpr) :
    (rawLowerPow b e).toExpr = lowerPow b.toExpr e.toExpr := by
  unfold rawLowerPow lowerPow
  by_cases ho : rawNumVal? e = some 1
  · rw [if_pos ho, if_pos ((rawNumVal_one_iff e).mp ho)]
  · rw [if_neg ho, if_neg (mt (rawNumVal_one_iff e).mpr ho)]; rfl

/-- The executable exact-ℚ lowerer embeds to the proved real lowerer. -/
theorem lowerRaw_toExpr (e : RawExpr) :
    (lowerRaw e).map RawExpr.toExpr = lower e.toExpr := by
  induction e with
  | num q t => rfl
  | var n => rfl
  | constant n => rfl
  | neg u ih =>
      cases hu : lowerRaw u with
      | none =>
          have hue : lower u.toExpr = none := by rw [← ih, hu]; rfl
          simp [lowerRaw, RawExpr.toExpr, lower, hu, hue]
      | some u' =>
          have hue : lower u.toExpr = some u'.toExpr := by rw [← ih, hu]; rfl
          simp [lowerRaw, RawExpr.toExpr, lower, hu, hue, rawLowerNeg_toExpr]
  | add l r ihl ihr =>
      cases hl : lowerRaw l with
      | none =>
          have hle : lower l.toExpr = none := by rw [← ihl, hl]; rfl
          simp [lowerRaw, RawExpr.toExpr, lower, hl, hle]
      | some l' =>
          have hle : lower l.toExpr = some l'.toExpr := by rw [← ihl, hl]; rfl
          cases hr : lowerRaw r with
          | none =>
              have hre : lower r.toExpr = none := by rw [← ihr, hr]; rfl
              simp [lowerRaw, RawExpr.toExpr, lower, hl, hr, hle, hre]
          | some r' =>
              have hre : lower r.toExpr = some r'.toExpr := by rw [← ihr, hr]; rfl
              simp [lowerRaw, RawExpr.toExpr, lower, hl, hr, hle, hre, rawLowerAdd_toExpr]
  | sub l r ihl ihr =>
      cases hl : lowerRaw l with
      | none =>
          have hle : lower l.toExpr = none := by rw [← ihl, hl]; rfl
          simp [lowerRaw, RawExpr.toExpr, lower, hl, hle]
      | some l' =>
          have hle : lower l.toExpr = some l'.toExpr := by rw [← ihl, hl]; rfl
          cases hr : lowerRaw r with
          | none =>
              have hre : lower r.toExpr = none := by rw [← ihr, hr]; rfl
              simp [lowerRaw, RawExpr.toExpr, lower, hl, hr, hle, hre]
          | some r' =>
              have hre : lower r.toExpr = some r'.toExpr := by rw [← ihr, hr]; rfl
              simp [lowerRaw, RawExpr.toExpr, lower, hl, hr, hle, hre, rawLowerSub_toExpr]
  | mul l r ihl ihr =>
      cases hl : lowerRaw l with
      | none =>
          have hle : lower l.toExpr = none := by rw [← ihl, hl]; rfl
          simp [lowerRaw, RawExpr.toExpr, lower, hl, hle]
      | some l' =>
          have hle : lower l.toExpr = some l'.toExpr := by rw [← ihl, hl]; rfl
          cases hr : lowerRaw r with
          | none =>
              have hre : lower r.toExpr = none := by rw [← ihr, hr]; rfl
              simp [lowerRaw, RawExpr.toExpr, lower, hl, hr, hle, hre]
          | some r' =>
              have hre : lower r.toExpr = some r'.toExpr := by rw [← ihr, hr]; rfl
              simp [lowerRaw, RawExpr.toExpr, lower, hl, hr, hle, hre, rawLowerMul_toExpr]
  | div l r ihl ihr =>
      cases hl : lowerRaw l with
      | none =>
          have hle : lower l.toExpr = none := by rw [← ihl, hl]; rfl
          simp [lowerRaw, RawExpr.toExpr, lower, hl, hle]
      | some l' =>
          have hle : lower l.toExpr = some l'.toExpr := by rw [← ihl, hl]; rfl
          cases hr : lowerRaw r with
          | none =>
              have hre : lower r.toExpr = none := by rw [← ihr, hr]; rfl
              simp [lowerRaw, RawExpr.toExpr, lower, hl, hr, hle, hre]
          | some r' =>
              have hre : lower r.toExpr = some r'.toExpr := by rw [← ihr, hr]; rfl
              simp [lowerRaw, RawExpr.toExpr, lower, hl, hr, hle, hre, rawLowerDiv_toExpr]
  | mod l r ihl ihr =>
      cases hl : lowerRaw l with
      | none =>
          have hle : lower l.toExpr = none := by rw [← ihl, hl]; rfl
          simp [lowerRaw, RawExpr.toExpr, lower, hl, hle]
      | some l' =>
          have hle : lower l.toExpr = some l'.toExpr := by rw [← ihl, hl]; rfl
          cases hr : lowerRaw r with
          | none =>
              have hre : lower r.toExpr = none := by rw [← ihr, hr]; rfl
              simp [lowerRaw, RawExpr.toExpr, lower, hl, hr, hle, hre]
          | some r' =>
              have hre : lower r.toExpr = some r'.toExpr := by rw [← ihr, hr]; rfl
              simp [lowerRaw, RawExpr.toExpr, lower, hl, hr, hle, hre, rawLowerMod_toExpr]
  | pow b e ihb ihe =>
      cases hb : lowerRaw b with
      | none =>
          have hbe : lower b.toExpr = none := by rw [← ihb, hb]; rfl
          simp [lowerRaw, RawExpr.toExpr, lower, hb, hbe]
      | some b' =>
          have hbe : lower b.toExpr = some b'.toExpr := by rw [← ihb, hb]; rfl
          cases he : lowerRaw e with
          | none =>
              have hee : lower e.toExpr = none := by rw [← ihe, he]; rfl
              simp [lowerRaw, RawExpr.toExpr, lower, hb, he, hbe, hee]
          | some e' =>
              have hee : lower e.toExpr = some e'.toExpr := by rw [← ihe, he]; rfl
              simp [lowerRaw, RawExpr.toExpr, lower, hb, he, hbe, hee, rawLowerPow_toExpr]
  | call1 n u ih =>
      cases hu : lowerRaw u with
      | none =>
          have hue : lower u.toExpr = none := by rw [← ih, hu]; rfl
          simp [lowerRaw, RawExpr.toExpr, lower, hu, hue]
      | some u' =>
          have hue : lower u.toExpr = some u'.toExpr := by rw [← ih, hu]; rfl
          simp [lowerRaw, RawExpr.toExpr, lower, hu, hue]
  | call2 n u v ihu ihv =>
      cases hu : lowerRaw u with
      | none =>
          have hue : lower u.toExpr = none := by rw [← ihu, hu]; rfl
          simp [lowerRaw, RawExpr.toExpr, lower, hu, hue]
      | some u' =>
          have hue : lower u.toExpr = some u'.toExpr := by rw [← ihu, hu]; rfl
          cases hv : lowerRaw v with
          | none =>
              have hve : lower v.toExpr = none := by rw [← ihv, hv]; rfl
              simp [lowerRaw, RawExpr.toExpr, lower, hu, hv, hue, hve]
          | some v' =>
              have hve : lower v.toExpr = some v'.toExpr := by rw [← ihv, hv]; rfl
              simp [lowerRaw, RawExpr.toExpr, lower, hu, hv, hue, hve]

/-! ### Exact certificate expression reconstruction -/

/-- Reconstruct the exact-rational expression rooted at `id`.  Unlike the
release s-expression, numeric meaning is retained and compared. -/
def buildRawExpr : Nat → List Node → Nat → Option RawExpr
  | 0, _, _ => none
  | fuel + 1, nodes, id =>
    match findNode nodes id with
    | none => none
    | some nd =>
      match nd.op, nd.children with
      | "num_exact", [] => some (RawExpr.num nd.value nd.name)
      | "num_rounded", [] => some (RawExpr.num nd.value nd.name)
      | "const_rounded", [] => some (RawExpr.constant nd.name)
      | "var", [] => some (RawExpr.var nd.name)
      | "neg", [c0] => (buildRawExpr fuel nodes c0).map (RawExpr.neg ·)
      | "powZero", [c0] =>
          (buildRawExpr fuel nodes c0).map (fun e => RawExpr.pow e (RawExpr.num (↑nd.n) nd.name))
      | "powEvenPos", [c0] =>
          (buildRawExpr fuel nodes c0).map (fun e => RawExpr.pow e (RawExpr.num (↑nd.n) nd.name))
      | "powOddPos", [c0] =>
          (buildRawExpr fuel nodes c0).map (fun e => RawExpr.pow e (RawExpr.num (↑nd.n) nd.name))
      | "powNegEven", [c0] =>
          (buildRawExpr fuel nodes c0).map (fun e => RawExpr.pow e (RawExpr.neg (RawExpr.num (↑nd.n) nd.name)))
      | "powNegOdd", [c0] =>
          (buildRawExpr fuel nodes c0).map (fun e => RawExpr.pow e (RawExpr.neg (RawExpr.num (↑nd.n) nd.name)))
      | "add", [c0, c1] =>
          match buildRawExpr fuel nodes c0, buildRawExpr fuel nodes c1 with
          | some a, some b => some (RawExpr.add a b) | _, _ => none
      | "sub", [c0, c1] =>
          match buildRawExpr fuel nodes c0, buildRawExpr fuel nodes c1 with
          | some a, some b => some (RawExpr.sub a b) | _, _ => none
      | "mul", [c0, c1] =>
          match buildRawExpr fuel nodes c0, buildRawExpr fuel nodes c1 with
          | some a, some b => some (RawExpr.mul a b) | _, _ => none
      | "div", [c0, c1] =>
          match buildRawExpr fuel nodes c0, buildRawExpr fuel nodes c1 with
          | some a, some b => some (RawExpr.div a b) | _, _ => none
      | "powGeneral", [c0, c1] =>
          match buildRawExpr fuel nodes c0, buildRawExpr fuel nodes c1 with
          | some a, some b => some (RawExpr.pow a b) | _, _ => none
      | op, ch =>
          if op ∈ call1Names then
            match ch with
            | [c0] => (buildRawExpr fuel nodes c0).map (RawExpr.call1 op ·)
            | _ => none
          else if op ∈ call2Names then
            match ch with
            | [c0, c1] =>
                match buildRawExpr fuel nodes c0, buildRawExpr fuel nodes c1 with
                | some a, some b => some (RawExpr.call2 op a b) | _, _ => none
            | _ => none
          else none

def rawExprOf (nodes : List Node) : Option RawExpr :=
  match rootId nodes with
  | none => none
  | some rid => buildRawExpr (nodes.length + 1) nodes rid

/-! ### Release-fragment policy

`checkCert` proves a larger internal model than JACKAL currently releases as
FORMAL.  In particular, it can validate negative/general powers and several
TCB-backed transcendental nodes.  Release mode must not inherit that larger
checker surface accidentally: every node is independently restricted here to
the exact constructor set represented by the current FORMAL inventory.
-/

/-- Node constructors admitted by the current request-bound FORMAL lane.
Everything not named here is rejected by the final wildcard. -/
def releaseNodeOp : String → Bool
  | "num_exact"     => true
  | "var"           => true
  -- `const_rounded` is deliberately EXCLUDED here (2026-08-15, §487-const audit).
  -- Its `value/fl_lo` fields are bound only by `ConstTCB` inside `ModelTCB`,
  -- which is a hypothesis of `request_bound_certified_release` and is NOT
  -- runtime-decidable in ℚ (see CertSound.lean:34-38). A crafted
  -- `const_rounded name="pi" value=0` node would otherwise earn a release
  -- ACCEPT while `π` lies outside the certified box — precisely the modeled
  -- untrusted-evaluator threat. `num_rounded` was already excluded for the
  -- analogous reason; the two rounding-TCB constructors are now handled
  -- consistently. Rebase constants onto `num_exact` (exact-ℚ literals) or
  -- expand the release lane later with a checker-side value-binding rule.
  | "neg"           => true
  | "add"           => true
  | "sub"           => true
  | "mul"           => true
  | "div"           => true
  | "powZero"       => true
  | "powEvenPos"    => true
  | "powOddPos"     => true
  | "sin"           => true
  | "cos"           => true
  | "abs"           => true
  | "floor"         => true
  | "ceil"          => true
  | "round"         => true
  | "trunc"         => true
  | "min"           => true
  | "max"           => true
  | _                 => false

/-- All certificate nodes belong to the exact released FORMAL fragment. -/
def releaseNodesOk (nodes : List Node) : Bool :=
  nodes.all (fun nd => releaseNodeOp nd.op)

/-- Exact request match.  Every conjunct is executable and fail-closed,
including the Lean-owned release-fragment allowlist. -/
def requestMatches (command rawExpr rawLo rawHi : String)
    (hdr : Header) (nodes : List Node) : Bool :=
  (command == rangeBoundCommand) &&
  ((hdr.status_class == "bounded") &&
  (releaseNodesOk nodes &&
  ((parseRatCanon rawLo.toList == some hdr.input_lo) &&
  ((parseRatCanon rawHi.toList == some hdr.input_hi) &&
    match parseRaw rawExpr, rawExprOf nodes with
    | some ast, some certExpr => lowerRaw ast == some certExpr
    | _, _ => false))))

/-! The bridge from `rawExprOf` to `exprOf` and the composed release theorem
are proved below. -/

set_option linter.unusedSimpArgs false in
theorem buildRawExpr_toExpr (fuel : Nat) (nodes : List Node) (id : Nat) :
    (buildRawExpr fuel nodes id).map RawExpr.toExpr = buildExpr fuel nodes id := by
  induction fuel generalizing id with
  | zero => rfl
  | succ fuel ih =>
      have ih' (j : Nat) : buildExpr fuel nodes j =
          (buildRawExpr fuel nodes j).map RawExpr.toExpr := (ih j).symm
      cases hfind : findNode nodes id with
      | none => simp [buildRawExpr, buildExpr, hfind]
      | some nd =>
          simp only [buildRawExpr, buildExpr, hfind]
          split <;>
            simp_all [RawExpr.toExpr, ih', Option.map_map, Function.comp_def] <;>
            repeat' first | split <;> simp_all [RawExpr.toExpr, ih', Option.map_map, Function.comp_def]
          all_goals
            by_cases h1 : nd.op ∈ call1Names
            · cases nd.children with
              | nil => simp [h1]
              | cons c cs =>
                  cases cs with
                  | nil => simp [h1, RawExpr.toExpr, Option.map_map, Function.comp_def]
                  | cons d ds => simp [h1]
            · by_cases h2 : nd.op ∈ call2Names
              · cases nd.children with
                | nil => simp [h1, h2]
                | cons c cs =>
                    cases cs with
                    | nil => simp [h1, h2]
                    | cons d ds =>
                        cases ds with
                        | nil =>
                            simp only [h1, h2, if_false, if_true]
                            cases buildRawExpr fuel nodes c <;>
                              cases buildRawExpr fuel nodes d <;> rfl
                        | cons e es => simp [h1, h2]
              · simp [h1, h2]

theorem rawExprOf_toExpr (nodes : List Node) :
    (rawExprOf nodes).map RawExpr.toExpr = exprOf nodes := by
  cases hroot : rootId nodes with
  | none => simp [rawExprOf, exprOf, hroot]
  | some rid => simp [rawExprOf, exprOf, hroot, buildRawExpr_toExpr]

/-- A true executable request match exposes the exact parsed/lowered tree and
the canonical limit/status equalities used by the release theorem. -/
theorem requestMatches_true {command rawExpr rawLo rawHi : String}
    {hdr : Header} {nodes : List Node}
    (h : requestMatches command rawExpr rawLo rawHi hdr nodes = true) :
    command = rangeBoundCommand ∧ hdr.status_class = "bounded" ∧
    releaseNodesOk nodes = true ∧
    parseRatCanon rawLo.toList = some hdr.input_lo ∧
    parseRatCanon rawHi.toList = some hdr.input_hi ∧
    ∃ ast lowered : RawExpr,
      parseRaw rawExpr = some ast ∧ lowerRaw ast = some lowered ∧
      rawExprOf nodes = some lowered := by
  unfold requestMatches at h
  simp only [Bool.and_eq_true, beq_iff_eq] at h
  rcases h with ⟨hcmd, hstatus, hfragment, hlo, hhi, htree⟩
  generalize hparse : parseRaw rawExpr = parsed at htree
  cases parsed with
  | none => simp at htree
  | some ast =>
      generalize hcert : rawExprOf nodes = cert at htree
      cases cert with
      | none => simp at htree
      | some certExpr =>
          have hlower : lowerRaw ast = some certExpr := by
            simpa using htree
          exact ⟨hcmd, hstatus, hfragment, hlo, hhi, ast, certExpr, rfl, hlower, rfl⟩

/-- A request-bound ACCEPT mechanically entails the exact node-level FORMAL
release policy; this fact does not depend on the external inventory file. -/
theorem requestMatches_releaseNodesOk {command rawExpr rawLo rawHi : String}
    {hdr : Header} {nodes : List Node}
    (h : requestMatches command rawExpr rawLo rawHi hdr nodes = true) :
    releaseNodesOk nodes = true :=
  (requestMatches_true h).2.2.1

/-! ### Kernel-reduced relabel controls -/

theorem requestMatches_valid :
    requestMatches "range-bound-cert" "-x" "2" "5" validHeader validNodes = true := by
  decide

theorem requestRejects_operation_relabel :
    requestMatches "integrate-bound" "-x" "2" "5" validHeader validNodes = false := by
  decide

theorem requestRejects_expression_relabel :
    requestMatches "range-bound-cert" "x" "2" "5" validHeader validNodes = false := by
  decide

theorem requestRejects_limit_relabel :
    requestMatches "range-bound-cert" "-x" "2" "6" validHeader validNodes = false := by
  decide

/-- Kernel-reduced inventory lock: every currently FORMAL node constructor is
admitted by the Lean release policy. -/
theorem releaseNodeOp_accepts_formal_inventory :
    ["num_exact", "var", "neg", "add", "sub", "mul", "div",
      "powZero", "powEvenPos", "powOddPos", "sin", "cos", "abs", "floor",
      "ceil", "round", "trunc", "min", "max"].all releaseNodeOp = true := by
  decide

/-- Kernel-reduced refusal lock for checker-supported constructors that are
outside the released FORMAL fragment.  The wildcard in `releaseNodeOp` also
rejects every unknown constructor. -/
theorem releaseNodeOp_rejects_policy_outside :
    ["const_rounded", "num_rounded", "powNegEven", "powNegOdd", "powGeneral",
      "sqrt", "exp", "ln", "atan", "asin", "acos", "hypot"].all
      (fun op => !releaseNodeOp op) = true := by
  decide

theorem requestRejects_powNegEven_node :
    requestMatches "range-bound-cert" "x^-2" "1" "2" validHeader
      [{ id := 0, op := "powNegEven", children := [], out_lo := 0, out_hi := 0 }] = false := by
  decide

theorem requestRejects_powNegOdd_node :
    requestMatches "range-bound-cert" "x^-3" "1" "2" validHeader
      [{ id := 0, op := "powNegOdd", children := [], out_lo := 0, out_hi := 0 }] = false := by
  decide

/-- End-to-end refusal lock for the §487-const audit exploit shape: a single
`const_rounded name="pi"` node (whose `value`/`fl_lo` are bound only by the
undischarged `ConstTCB` premise) can never earn a request-bound release ACCEPT. -/
theorem requestRejects_const_rounded_node :
    requestMatches "range-bound-cert" "pi" "1" "2" validHeader
      [{ id := 0, op := "const_rounded", name := "pi", children := [],
         out_lo := 0, out_hi := 0 }] = false := by
  decide

theorem requestRejects_powGeneral_node :
    requestMatches "range-bound-cert" "x^x" "1" "2" validHeader
      [{ id := 0, op := "powGeneral", children := [], out_lo := 0, out_hi := 0 }] = false := by
  decide

/-- A cert-only-valid node whose printed token says `2` while its exact
semantic value says `3`.  The old s-expression-only bind could not distinguish
those meanings; the exact-rational request matcher does. -/
def numericRelabelNodes : List Node :=
  [{ id := 0, op := "num_exact", children := [], out_lo := 3, out_hi := 3,
     name := "2", value := 3 }]

def numericRelabelHeader : Header :=
  { schema_version := 2
    model_const_version := pinnedModelConst
    expr_commitment := "(num 2)"
    source_commitment := ""
    input_lo := 0, input_hi := 1
    root_id := 0
    output_lo := 3, output_hi := 3
    exe_identity := ""
    status_class := "bounded" }

theorem numericRelabel_certOnlyChecks :
    checkCert numericRelabelHeader numericRelabelNodes = true := by decide

theorem numericRelabel_exactTrees_differ :
    RawExpr.num 2 "2" ≠ RawExpr.num 3 "2" := by decide

/-- REQUEST-BOUND RELEASE.  If the executable request matcher and certificate
checker both accept, the exact expression denoted by the raw request is
enclosed on the exact canonical request interval, under the existing named
`ModelTCB`. -/
theorem request_bound_certified_release
    {command rawExpr rawLo rawHi : String} {hdr : Header} {nodes : List Node}
    (hreq : requestMatches command rawExpr rawLo rawHi hdr nodes = true)
    (hchk : checkCert hdr nodes = true) (htcb : ModelTCB hdr nodes)
    (hab : (↑hdr.input_lo : ℝ) ≤ ↑hdr.input_hi) :
    ∃ ast : Expr, Parser.parse rawExpr = some ast ∧
      ∀ x ∈ Set.Icc (↑hdr.input_lo : ℝ) (↑hdr.input_hi),
        DefinedOn ast x → sem ast x ∈ Set.Icc (↑hdr.output_lo : ℝ) (↑hdr.output_hi) := by
  obtain ⟨_, _, _, _, _, rawAst, lowered, hparseRaw, hlowerRaw, hcertRaw⟩ :=
    requestMatches_true hreq
  let ast := rawAst.toExpr
  let e := lowered.toExpr
  have hparse : Parser.parse rawExpr = some ast := by
    simp [Parser.parse, hparseRaw, ast]
  have hlower : lower ast = some e := by
    have h := lowerRaw_toExpr rawAst
    rw [hlowerRaw] at h
    simpa [ast, e] using h.symm
  have hex : exprOf nodes = some e := by
    have h := rawExprOf_toExpr nodes
    rw [hcertRaw] at h
    simpa [e] using h.symm
  have hrun : Runs e (↑hdr.input_lo, ↑hdr.input_hi)
      (↑hdr.output_lo, ↑hdr.output_hi) := cert_check_sound hchk hex htcb
  refine ⟨ast, hparse, ?_⟩
  exact parse_lower_encloses hparse hlower hrun hab

#print axioms request_bound_certified_release

end JackalIv.Cert
