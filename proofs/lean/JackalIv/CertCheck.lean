/-
JackalIv/CertCheck.lean — the COMPUTABLE certificate checker.

This file defines the fail-closed, genuinely-computable `checkCert : Header →
List Node → Bool` promised by `CERT_DESIGN.md`.  It is built entirely from
`ℚ`/`Bool`/`Nat`/`Int`/`String` operations — NO `Real`, NO `noncomputable`, NO
`native_decide`/`@[implemented_by]` on any trust path — so it compiles from its
proved definition and the soundness theorem (a downstream deliverable) can be
stated against the SAME function the executable runs.

The checker has three passes (see `checkCert`):

1. `structuralOk` — determinism / well-formedness: `schema_version = 1`; the
   pinned `model_const_version`; unique node ids; every child id present and
   STRICTLY BELOW its parent id (⇒ acyclic + topological, so the maximal id is
   the unique root); `rootId = header.root_id`; the root referenced by no
   node; full reachability from the root; and `header output = root out`.
2. `nodes.all (checkNode header nodes ·)` — the per-op semantic pass.  For each
   of the 23 rational-exact `Runs` constructors it verifies that `out` equals
   the exact interval formula over the children's `out` and the recorded
   floats, discharging every `Approx` obligation with `algApproxQ` over `ℚ`
   and padding with `padLoQ`/`padHiQ` (all from `CertTypes`).  For the 8
   transcendental constructors (sqrt/exp/ln/atan/asin/acos/hypot/powGeneral) it
   verifies ONLY the structural padding and the domain/parity guards — the libm
   `Approx` facts are the disclosed `LibmModel` TCB, never re-decided here.
3. the expression-commitment bind: `sexpOf nodes` recomputes the engine
   `ast_sexp` string DIRECTLY from the node tree (mirroring
   `Parser.exprToSexp ∘ CertTypes.buildExpr` without ever materializing a real)
   and requires it to equal `header.expr_commitment`.

Unsupported ops (tan/cbrt/log10/log2/mod/unknown call) have no arm and fail
closed (`false`), exactly as they have no `Runs` constructor.

Sanity lemmas at the bottom pin the checker's behaviour on concrete certs:
a valid two-node cert checks `true`; a duplicate-id, a cycle (child id ≥ parent
id), a mutated node output, and a mismatched expression commitment each check
`false`.  These are discharged by `decide` — the checker genuinely reduces in
the kernel on exact (pad-free) certs.

No `sorry`/`admit`/axiom/`native_decide`/`unsafe`/`@[implemented_by]`.
-/
import JackalIv.CertTypes

namespace JackalIv.Cert

open JackalIv

/-! ### Pinned checker constants -/

/-- The pinned model-constant version.  A cert whose `model_const_version`
does not match this string is rejected (it pins `ε,τ,δ0,δlib,σ0`). -/
def pinnedModelConst : String := "jackal-iv-model-v1"

/-- Rational basic-op relative bound (matches `Model.δ0 = 1/2^53`). -/
def δ0Q : ℚ := 1 / 2 ^ 53

/-- Rational libm relative bound (matches `Model.δlib = 1/2^51`). -/
def δlibQ : ℚ := 1 / 2 ^ 51

/-- Rational subnormal absolute bound (matches `Model.σ0 = 1/2^1075`). -/
def σ0Q : ℚ := 1 / 2 ^ 1075

/-! ### Rational mirrors of the exact interval helpers

Each mirrors a `Syntax.lean`/`Pow.lean`/`Exact.lean` real helper over `ℚ`, so
the per-op check is a decidable rational computation. -/

/-- Decidable rational equality as a `Bool` (kernel-reducible on literals). -/
def eqQ (a b : ℚ) : Bool := decide (a = b)

/-- Rational mignitude — mirror of `Pow.mig`. -/
def migQ (xl xu : ℚ) : ℚ := if xl ≤ 0 ∧ 0 ≤ xu then 0 else min |xl| |xu|

/-- Rational magnitude — mirror of `Pow.mag`. -/
def magQ (xl xu : ℚ) : ℚ := max |xl| |xu|

/-- Rational `absLo` — mirror of `Exact.absLo`. -/
def absLoQ (l u : ℚ) : ℚ := if 0 ≤ l then l else if u ≤ 0 then -u else 0

/-- Rational `absHi` — mirror of `Exact.absHi`. -/
def absHiQ (l u : ℚ) : ℚ := if 0 ≤ l then u else if u ≤ 0 then -l else max (-l) u

/-- Rational truncation toward zero — mirror of `Exact.truncR`. -/
def truncRQ (x : ℚ) : ℚ := if 0 ≤ x then ((⌊x⌋ : ℤ) : ℚ) else ((⌈x⌉ : ℤ) : ℚ)

/-- Rational round-half-away-from-zero — mirror of `Exact.roundAway`. -/
def roundAwayQ (x : ℚ) : ℚ :=
  if 0 ≤ x then ((⌊x + 1 / 2⌋ : ℤ) : ℚ) else ((⌈x - 1 / 2⌉ : ℤ) : ℚ)

/-- Denominator-sign guard for `div`/`atan2`/`powNeg`: `den_sign = +1` witnesses
`0 < l₂` (denominator interval strictly positive); `den_sign = -1` witnesses
`u₂ < 0` (strictly negative); anything else is rejected. -/
def denSignOk (s : Int) (l u : ℚ) : Bool :=
  if s == 1 then decide (0 < l)
  else if s == -1 then decide (u < 0)
  else false

/-- Whether `name` is a pinned known constant (pi/e/tau). -/
def isKnownConst (name : String) : Bool :=
  name == "pi" || name == "e" || name == "tau"

/-! ### Expression-commitment recomputation (`sexpOf`)

`sexpBuild` produces the engine `ast_sexp` string directly from the node tree,
structurally mirroring `CertTypes.buildExpr` and printing exactly what
`Parser.exprToSexp` prints for the reconstructed `Expr` — but over strings only,
so the whole thing stays computable (no `Real` cast). -/

/-- Build the `ast_sexp` string rooted at node `id`, with `fuel` budget. -/
def sexpBuild : Nat → List Node → Nat → Option String
  | 0, _, _ => none
  | fuel + 1, nodes, id =>
    match findNode nodes id with
    | none => none
    | some nd =>
      match nd.op, nd.children with
      | "num_exact",    []  => some ("(num " ++ nd.name ++ ")")
      | "num_rounded",  []  => some ("(num " ++ nd.name ++ ")")
      | "const_rounded",[]  => some ("(const " ++ nd.name ++ ")")
      | "var",          []  => some ("(var " ++ nd.name ++ ")")
      | "neg", [c0] => (sexpBuild fuel nodes c0).map (fun s => "(neg " ++ s ++ ")")
      | "powZero",    [c0] =>
          (sexpBuild fuel nodes c0).map (fun s => "(pow " ++ s ++ " (num " ++ nd.name ++ "))")
      | "powEvenPos", [c0] =>
          (sexpBuild fuel nodes c0).map (fun s => "(pow " ++ s ++ " (num " ++ nd.name ++ "))")
      | "powOddPos",  [c0] =>
          (sexpBuild fuel nodes c0).map (fun s => "(pow " ++ s ++ " (num " ++ nd.name ++ "))")
      | "powNegEven", [c0] =>
          (sexpBuild fuel nodes c0).map (fun s => "(pow " ++ s ++ " (neg (num " ++ nd.name ++ ")))")
      | "powNegOdd",  [c0] =>
          (sexpBuild fuel nodes c0).map (fun s => "(pow " ++ s ++ " (neg (num " ++ nd.name ++ ")))")
      -- sqrt_rat prints as `(call sqrt …)` — the strategy annotation lives on
      -- the certificate node type, not in the reconstructed expression sexp.
      | "sqrt_rat", [c0] =>
          (sexpBuild fuel nodes c0).map (fun s => "(call sqrt " ++ s ++ ")")
      | "add", [c0, c1] =>
          match sexpBuild fuel nodes c0, sexpBuild fuel nodes c1 with
          | some a, some b => some ("(add " ++ a ++ " " ++ b ++ ")") | _, _ => none
      | "sub", [c0, c1] =>
          match sexpBuild fuel nodes c0, sexpBuild fuel nodes c1 with
          | some a, some b => some ("(sub " ++ a ++ " " ++ b ++ ")") | _, _ => none
      | "mul", [c0, c1] =>
          match sexpBuild fuel nodes c0, sexpBuild fuel nodes c1 with
          | some a, some b => some ("(mul " ++ a ++ " " ++ b ++ ")") | _, _ => none
      | "div", [c0, c1] =>
          match sexpBuild fuel nodes c0, sexpBuild fuel nodes c1 with
          | some a, some b => some ("(div " ++ a ++ " " ++ b ++ ")") | _, _ => none
      | "powGeneral", [c0, c1] =>
          match sexpBuild fuel nodes c0, sexpBuild fuel nodes c1 with
          | some a, some b => some ("(pow " ++ a ++ " " ++ b ++ ")") | _, _ => none
      | op, ch =>
          if op ∈ call1Names then
            match ch with
            | [c0] => (sexpBuild fuel nodes c0).map (fun s => "(call " ++ op ++ " " ++ s ++ ")")
            | _    => none
          else if op ∈ call2Names then
            match ch with
            | [c0, c1] =>
                match sexpBuild fuel nodes c0, sexpBuild fuel nodes c1 with
                | some a, some b => some ("(call " ++ op ++ " " ++ a ++ " " ++ b ++ ")") | _, _ => none
            | _ => none
          else none

/-- Recompute the engine `ast_sexp` for the whole cert (rooted at the maximal
id).  `none` on any structural failure (fail-closed). -/
def sexpOf (nodes : List Node) : Option String :=
  match rootId nodes with
  | none     => none
  | some rid => sexpBuild (nodes.length + 1) nodes rid

/-! ### The structural pass -/

/-- Boolean "no duplicates" on a `Nat` id list. -/
def nodupIds : List Nat → Bool
  | []      => true
  | x :: xs => (!xs.contains x) && nodupIds xs

/-- Every child of `nd` is present and strictly below `nd.id` (⇒ acyclic +
topological). -/
def childrenOk (nodes : List Node) (nd : Node) : Bool :=
  nd.children.all (fun c => (findNode nodes c).isSome && decide (c < nd.id))

/-- No node lists `rid` among its children — the root is unreferenced. -/
def rootUnreferenced (nodes : List Node) (rid : Nat) : Bool :=
  nodes.all (fun nd => !nd.children.contains rid)

/-- One monotone reachability expansion step: append every not-yet-seen child
of a currently-reached node. -/
def reachStep (nodes : List Node) (acc : List Nat) : List Nat :=
  acc ++ acc.flatMap (fun i =>
    match findNode nodes i with
    | some nd => nd.children.filter (fun c => !acc.contains c)
    | none    => [])

/-- Fuel-bounded reachability closure from the current frontier. -/
def reachClosure (nodes : List Node) : Nat → List Nat → List Nat
  | 0,        acc => acc
  | fuel + 1, acc => reachClosure nodes fuel (reachStep nodes acc)

/-- The set of ids reachable from the header root (bounded by `|nodes|` steps,
which suffices because every child id is strictly below its parent). -/
def reachableIds (hdr : Header) (nodes : List Node) : List Nat :=
  reachClosure nodes nodes.length [hdr.root_id]

/-- The determinism / well-formedness pass.  Rejects on any violation. -/
def structuralOk (hdr : Header) (nodes : List Node) : Bool :=
  decide (hdr.schema_version = 2) &&
  (hdr.model_const_version == pinnedModelConst) &&
  (!nodes.isEmpty) &&
  nodupIds (nodes.map (·.id)) &&
  nodes.all (fun nd => childrenOk nodes nd) &&
  (match rootId nodes with
   | some r => decide (r = hdr.root_id)
   | none   => false) &&
  (findNode nodes hdr.root_id).isSome &&
  rootUnreferenced nodes hdr.root_id &&
  (match findNode nodes hdr.root_id with
   | some root => eqQ hdr.output_lo root.out_lo && eqQ hdr.output_hi root.out_hi
   | none      => false) &&
  (let reach := reachableIds hdr nodes
   nodes.all (fun nd => reach.contains nd.id))

/-! ### The per-op semantic pass -/

/-- The per-node semantic check.  For each supported op, verify that `out`
equals the exact interval formula over the children's `out` and the recorded
floats (with `algApproxQ` discharging each `Approx` obligation over `ℚ`), or —
for the 8 transcendentals — the structural padding and guards only.  Any
unsupported op or arity mismatch fails closed. -/
def checkNode (hdr : Header) (nodes : List Node) (nd : Node) : Bool :=
  match nd.op, nd.children with
  -- leaves
  | "num_exact", [] =>
      eqQ nd.out_lo nd.value && eqQ nd.out_hi nd.value
  | "num_rounded", [] =>
      eqQ nd.out_lo (padLoQ nd.fl_lo) && eqQ nd.out_hi (padHiQ nd.fl_lo) &&
      algApproxQ nd.fl_lo nd.value δ0Q σ0Q
  | "const_rounded", [] =>
      isKnownConst nd.name &&
      eqQ nd.out_lo (padLoQ nd.fl_lo) && eqQ nd.out_hi (padHiQ nd.fl_lo) &&
      algApproxQ nd.fl_lo nd.value δ0Q σ0Q
  | "var", [] =>
      (nd.name == "x") && eqQ nd.out_lo hdr.input_lo && eqQ nd.out_hi hdr.input_hi
  -- unary exact
  | "neg", [c0] =>
      match childOut nodes c0 with
      | some (l, u) => eqQ nd.out_lo (-u) && eqQ nd.out_hi (-l)
      | none        => false
  -- binary rounded arithmetic
  | "add", [c0, c1] =>
      match childOut nodes c0, childOut nodes c1 with
      | some (l₁, u₁), some (l₂, u₂) =>
          eqQ nd.out_lo (padLoQ nd.fl_lo) && eqQ nd.out_hi (padHiQ nd.fl_hi) &&
          algApproxQ nd.fl_lo (l₁ + l₂) δ0Q σ0Q && algApproxQ nd.fl_hi (u₁ + u₂) δ0Q σ0Q
      | _, _ => false
  | "sub", [c0, c1] =>
      match childOut nodes c0, childOut nodes c1 with
      | some (l₁, u₁), some (l₂, u₂) =>
          eqQ nd.out_lo (padLoQ nd.fl_lo) && eqQ nd.out_hi (padHiQ nd.fl_hi) &&
          algApproxQ nd.fl_lo (l₁ - u₂) δ0Q σ0Q && algApproxQ nd.fl_hi (u₁ - l₂) δ0Q σ0Q
      | _, _ => false
  | "mul", [c0, c1] =>
      match childOut nodes c0, childOut nodes c1 with
      | some (l₁, u₁), some (l₂, u₂) =>
          eqQ nd.out_lo (padLoQ (min (min nd.p1 nd.p2) (min nd.p3 nd.p4))) &&
          eqQ nd.out_hi (padHiQ (max (max nd.p1 nd.p2) (max nd.p3 nd.p4))) &&
          algApproxQ nd.p1 (l₁ * l₂) δ0Q σ0Q && algApproxQ nd.p2 (l₁ * u₂) δ0Q σ0Q &&
          algApproxQ nd.p3 (u₁ * l₂) δ0Q σ0Q && algApproxQ nd.p4 (u₁ * u₂) δ0Q σ0Q
      | _, _ => false
  | "div", [c0, c1] =>
      match childOut nodes c0, childOut nodes c1 with
      | some (l₁, u₁), some (l₂, u₂) =>
          denSignOk nd.den_sign l₂ u₂ &&
          eqQ nd.out_lo (padLoQ (min (min nd.p1 nd.p2) (min nd.p3 nd.p4))) &&
          eqQ nd.out_hi (padHiQ (max (max nd.p1 nd.p2) (max nd.p3 nd.p4))) &&
          algApproxQ nd.p1 (l₁ / l₂) δ0Q σ0Q && algApproxQ nd.p2 (l₁ / u₂) δ0Q σ0Q &&
          algApproxQ nd.p3 (u₁ / l₂) δ0Q σ0Q && algApproxQ nd.p4 (u₁ / u₂) δ0Q σ0Q
      | _, _ => false
  -- integer powers
  | "powZero", [c0] =>
      match childOut nodes c0 with
      | some _ => (nd.n == 0) && eqQ nd.out_lo 1 && eqQ nd.out_hi 1
      | none   => false
  | "powEvenPos", [c0] =>
      match childOut nodes c0 with
      | some (l, u) =>
          (nd.n % 2 == 0) && decide (2 ≤ nd.n) &&
          eqQ nd.out_lo (padLoQ nd.fl_lo) && eqQ nd.out_hi (padHiQ nd.fl_hi) &&
          algApproxQ nd.fl_lo (migQ l u ^ nd.n) δlibQ σ0Q &&
          algApproxQ nd.fl_hi (magQ l u ^ nd.n) δlibQ σ0Q
      | none => false
  | "powOddPos", [c0] =>
      match childOut nodes c0 with
      | some (l, u) =>
          (nd.n % 2 == 1) &&
          eqQ nd.out_lo (padLoQ nd.fl_lo) && eqQ nd.out_hi (padHiQ nd.fl_hi) &&
          algApproxQ nd.fl_lo (l ^ nd.n) δlibQ σ0Q &&
          algApproxQ nd.fl_hi (u ^ nd.n) δlibQ σ0Q
      | none => false
  | "powNegEven", [c0] =>
      match childOut nodes c0 with
      | some (l, u) =>
          let cl := padLoQ nd.fl_lo
          let cu := padHiQ nd.fl_hi
          (nd.n % 2 == 0) && decide (2 ≤ nd.n) &&
          algApproxQ nd.fl_lo (migQ l u ^ nd.n) δlibQ σ0Q &&
          algApproxQ nd.fl_hi (magQ l u ^ nd.n) δlibQ σ0Q &&
          denSignOk nd.den_sign cl cu &&
          eqQ nd.out_lo (padLoQ (min (min nd.p1 nd.p2) (min nd.p3 nd.p4))) &&
          eqQ nd.out_hi (padHiQ (max (max nd.p1 nd.p2) (max nd.p3 nd.p4))) &&
          algApproxQ nd.p1 (1 / cl) δ0Q σ0Q && algApproxQ nd.p2 (1 / cu) δ0Q σ0Q &&
          algApproxQ nd.p3 (1 / cl) δ0Q σ0Q && algApproxQ nd.p4 (1 / cu) δ0Q σ0Q
      | none => false
  | "powNegOdd", [c0] =>
      match childOut nodes c0 with
      | some (l, u) =>
          let cl := padLoQ nd.fl_lo
          let cu := padHiQ nd.fl_hi
          (nd.n % 2 == 1) &&
          algApproxQ nd.fl_lo (l ^ nd.n) δlibQ σ0Q &&
          algApproxQ nd.fl_hi (u ^ nd.n) δlibQ σ0Q &&
          denSignOk nd.den_sign cl cu &&
          eqQ nd.out_lo (padLoQ (min (min nd.p1 nd.p2) (min nd.p3 nd.p4))) &&
          eqQ nd.out_hi (padHiQ (max (max nd.p1 nd.p2) (max nd.p3 nd.p4))) &&
          algApproxQ nd.p1 (1 / cl) δ0Q σ0Q && algApproxQ nd.p2 (1 / cu) δ0Q σ0Q &&
          algApproxQ nd.p3 (1 / cl) δ0Q σ0Q && algApproxQ nd.p4 (1 / cu) δ0Q σ0Q
      | none => false
  -- universal-hull trig (no Approx, no TCB)
  | "sin", [c0] =>
      match childOut nodes c0 with
      | some _ => eqQ nd.out_lo (-1) && eqQ nd.out_hi 1
      | none   => false
  | "cos", [c0] =>
      match childOut nodes c0 with
      | some _ => eqQ nd.out_lo (-1) && eqQ nd.out_hi 1
      | none   => false
  -- exact scalar / lattice ops
  | "abs", [c0] =>
      match childOut nodes c0 with
      | some (l, u) => eqQ nd.out_lo (absLoQ l u) && eqQ nd.out_hi (absHiQ l u)
      | none        => false
  | "floor", [c0] =>
      match childOut nodes c0 with
      | some (l, u) => eqQ nd.out_lo ((⌊l⌋ : ℤ) : ℚ) && eqQ nd.out_hi ((⌊u⌋ : ℤ) : ℚ)
      | none        => false
  | "ceil", [c0] =>
      match childOut nodes c0 with
      | some (l, u) => eqQ nd.out_lo ((⌈l⌉ : ℤ) : ℚ) && eqQ nd.out_hi ((⌈u⌉ : ℤ) : ℚ)
      | none        => false
  | "round", [c0] =>
      match childOut nodes c0 with
      | some (l, u) => eqQ nd.out_lo (roundAwayQ l) && eqQ nd.out_hi (roundAwayQ u)
      | none        => false
  | "trunc", [c0] =>
      match childOut nodes c0 with
      | some (l, u) => eqQ nd.out_lo (truncRQ l) && eqQ nd.out_hi (truncRQ u)
      | none        => false
  | "min", [c0, c1] =>
      match childOut nodes c0, childOut nodes c1 with
      | some (l₁, u₁), some (l₂, u₂) => eqQ nd.out_lo (min l₁ l₂) && eqQ nd.out_hi (min u₁ u₂)
      | _, _ => false
  | "max", [c0, c1] =>
      match childOut nodes c0, childOut nodes c1 with
      | some (l₁, u₁), some (l₂, u₂) => eqQ nd.out_lo (max l₁ l₂) && eqQ nd.out_hi (max u₁ u₂)
      | _, _ => false
  -- transcendentals: structural padding + guards ONLY (Approx ⇒ LibmModel TCB)
  | "sqrt", [c0] =>
      match childOut nodes c0 with
      | some (l, _) =>
          decide (0 ≤ l) &&
          eqQ nd.out_lo (max (padLoQ nd.fl_lo) 0) && eqQ nd.out_hi (padHiQ nd.fl_hi)
      | none => false
  | "exp", [c0] =>
      match childOut nodes c0 with
      | some _ => eqQ nd.out_lo (padLoQ nd.fl_lo) && eqQ nd.out_hi (padHiQ nd.fl_hi)
      | none   => false
  | "ln", [c0] =>
      match childOut nodes c0 with
      | some (l, _) =>
          decide (0 < l) &&
          eqQ nd.out_lo (padLoQ nd.fl_lo) && eqQ nd.out_hi (padHiQ nd.fl_hi)
      | none => false
  | "atan", [c0] =>
      match childOut nodes c0 with
      | some _ => eqQ nd.out_lo (padLoQ nd.fl_lo) && eqQ nd.out_hi (padHiQ nd.fl_hi)
      | none   => false
  | "asin", [c0] =>
      match childOut nodes c0 with
      | some (l, u) =>
          decide (-1 ≤ l ∧ u ≤ 1) &&
          eqQ nd.out_lo (padLoQ nd.fl_lo) && eqQ nd.out_hi (padHiQ nd.fl_hi)
      | none => false
  | "acos", [c0] =>
      match childOut nodes c0 with
      | some (l, u) =>
          decide (-1 ≤ l ∧ u ≤ 1) &&
          eqQ nd.out_lo (padLoQ nd.fl_hi) && eqQ nd.out_hi (padHiQ nd.fl_lo)
      | none => false
  | "hypot", [c0, c1] =>
      match childOut nodes c0, childOut nodes c1 with
      | some _, some _ => eqQ nd.out_lo (padLoQ nd.fl_lo) && eqQ nd.out_hi (padHiQ nd.fl_hi)
      | _, _ => false
  | "powGeneral", [c0, c1] =>
      match childOut nodes c0, childOut nodes c1 with
      | some (xl, _), some _ => decide (0 < xl) && eqQ nd.out_lo nd.El && eqQ nd.out_hi nd.Eu
      | _, _ => false
  -- Pure-ℚ sqrt (no libm TCB): `Runs.sqrtRat`, §487 fragment extension.
  -- Placed LAST (just before the wildcard) so the checkNode split cases align
  -- with CertSound's bullet order.  The checked cert node's `out_lo`/`out_hi`
  -- ARE the emitter's proposed `loQ`/`hiQ`.
  | "sqrt_rat", [c0] =>
      match childOut nodes c0 with
      | some (l, u) =>
          decide (0 ≤ nd.out_lo) && decide (0 ≤ nd.out_hi) &&
          decide (nd.out_lo ^ 2 ≤ l) && decide (u ≤ nd.out_hi ^ 2)
      | none => false
  -- fail closed
  | _, _ => false

/-! ### The whole checker -/

/-- The full certificate checker: structural pass, per-node semantic pass, and
the expression-commitment bind.  Genuinely computable (`ℚ`/`Bool`/`Nat`/`Int`/
`String` only), so it compiles from this proved definition. -/
def checkCert (hdr : Header) (nodes : List Node) : Bool :=
  structuralOk hdr nodes &&
  nodes.all (fun nd => checkNode hdr nodes nd) &&
  (match sexpOf nodes with
   | some s => s == hdr.expr_commitment
   | none   => false)

/-! ### Sanity certificates and reduction lemmas

The checker reduces in the kernel on exact (pad-free) certs, so these are
discharged by `decide` (no `native_decide`).  The expression is `neg (var x)`:
node 0 is `var x` over the input box, node 1 is its negation and the root. -/

/-- A well-formed two-node cert for `neg(var x)` over input `[2, 5]`, output
`[-5, -2]`. -/
def validNodes : List Node :=
  [ { id := 0, op := "var", children := [], out_lo := 2, out_hi := 5, name := "x" },
    { id := 1, op := "neg", children := [0], out_lo := -5, out_hi := -2 } ]

/-- The matching header. -/
def validHeader : Header :=
  { schema_version := 2
    model_const_version := pinnedModelConst
    expr_commitment := "(neg (var x))"
    source_commitment := ""
    input_lo := 2, input_hi := 5
    root_id := 1
    output_lo := -5, output_hi := -2
    exe_identity := ""
    status_class := "bounded" }

/-- SANITY: the valid cert checks `true`. -/
theorem checkCert_valid : checkCert validHeader validNodes = true := by decide

/-- SANITY: the recomputed expression commitment matches the header. -/
theorem sexpOf_valid : sexpOf validNodes = some "(neg (var x))" := by decide

/-- A cert with a DUPLICATE node id (two nodes share id `1`). -/
def dupNodes : List Node :=
  [ { id := 1, op := "var", children := [], out_lo := 2, out_hi := 5, name := "x" },
    { id := 1, op := "neg", children := [0], out_lo := -5, out_hi := -2 } ]

/-- SANITY: a duplicate-id cert is rejected. -/
theorem checkCert_dup : checkCert validHeader dupNodes = false := by decide

/-- A cert with a CYCLE: node `1` points to `2` and node `2` points back to `1`,
so a child id is not strictly below its parent id (topological check fails). -/
def cycleNodes : List Node :=
  [ { id := 1, op := "neg", children := [2], out_lo := -5, out_hi := -2 },
    { id := 2, op := "neg", children := [1], out_lo := 2, out_hi := 5 } ]

/-- The header naming the cyclic cert's root. -/
def cycleHeader : Header :=
  { validHeader with root_id := 2, output_lo := 2, output_hi := 5 }

/-- SANITY: a cyclic cert (child id ≥ parent id) is rejected. -/
theorem checkCert_cycle : checkCert cycleHeader cycleNodes = false := by decide

/-- The valid cert with node 0's lower output MUTATED (`2 ↦ 99`), so both the
`var` and the `neg` semantic checks fail. -/
def mutatedNodes : List Node :=
  [ { id := 0, op := "var", children := [], out_lo := 99, out_hi := 5, name := "x" },
    { id := 1, op := "neg", children := [0], out_lo := -5, out_hi := -2 } ]

/-- SANITY: a cert with a mutated node output is rejected. -/
theorem checkCert_mutated : checkCert validHeader mutatedNodes = false := by decide

/-- SANITY: a valid structure with a WRONG expression commitment is rejected
(the commitment bind fails even though structure and semantics pass). -/
theorem checkCert_wrong_commitment :
    checkCert { validHeader with expr_commitment := "(var x)" } validNodes = false := by
  decide

/-- SANITY: the checker is decidable-by-reduction — `checkCert` on the valid
cert is definitionally `true` (no classical reasoning needed). -/
example : checkCert validHeader validNodes = true := by decide

end JackalIv.Cert
