/-
JackalIv/ShadowCertCheck.lean — SHADOW (research-shadow, NON-AUTHORITATIVE).

The COMPUTABLE composition checker for the v1.7 `bound_step` subdivision-tree
artifact.  Genuinely computable (`ℚ`/`Bool`/`Nat`/`String` only) and
reason-carrying: every refusal returns a stable reason class string
`<class>[:<detail>]` with `<class>` one of

  malformed-artifact, noncanonical-value, stale-identity, malformed-tree,
  invalid-interval, request-mismatch, unsupported-leaf-mode, missing-premise,
  forged-enclosure, child-partition-mismatch, forged-parent-sum,
  budget-exhausted, depth-exhausted, policy-violation, tolerance-unmet,
  released-interval-mismatch

(the codec layer produces malformed-artifact / noncanonical-value; this file
produces the rest).

Design (mission §6.3, §6.4):
  * FLAT per-node semantic pass (mirrors `Cert.checkCert`'s discipline; no
    recursion on untrusted structure, so no adversarial blowup).
  * Structural pass: unique ids; every child exists with id strictly below
    its parent (topological ⇒ acyclic; forward/self references refuse);
    unique root = maximal id = header root; root unreferenced; every non-root
    node referenced exactly once (no sharing); full reachability (no
    orphans); BFS depth ≤ 60; node count ≤ 60001 (the engine's entry-check
    budget semantics).
  * Per-leaf pass: role-ordered embedded certificates each accepted by the
    EXISTING proved `Cert.checkCert`; expression chain bound to the mirror
    differentiator `DQiter`; interval binding (full subinterval, or exact
    midpoint containment for Fm/F2m); enclosure conservativity against the
    exact-ℚ ideals of the shipped accepted forms (range / taylor2 / taylor4,
    including the engine's range∩taylor intersection); the engine's local
    tolerance policy `width ≤ (9/10)·tol·(b−a)/span` in exact ℚ.
  * Per-split pass: exactly two children; exact partition equalities
    `l.a = p.a ∧ l.b = r.a ∧ r.b = p.b` (order-binding: silent swaps, gaps,
    and overlaps all refuse); parent-sum conservativity
    `p.lo ≤ l.lo + r.lo ∧ l.hi + r.hi ≤ p.hi`.
  * Header pass: pinned schema/model/checker/status identities; request
    well-formedness; root domain = request domain; released interval is an
    outward extension of the root claim; released width ≤ tolerance.

No `sorry`, no axiom, no `native_decide`, no `@[implemented_by]`.
-/
import JackalIv.ShadowCertTypes

namespace JackalIv.Shadow

open JackalIv

/-! ### Reason-carrying guards -/

/-- Boolean guard with a stable refusal reason. -/
def guardE (c : Bool) (reason : String) : Except String Unit :=
  if c then .ok () else .error reason

/-- Fold a reason-carrying check over a list. -/
def allE {α : Type} (f : α → Except String Unit) : List α → Except String Unit
  | [] => .ok ()
  | x :: xs => do
      f x
      allE f xs

/-! ### Structural pass -/

/-- Boolean "no duplicates" on a `Nat` list (mirror of `Cert.nodupIds`). -/
def nodupNats : List Nat → Bool
  | [] => true
  | x :: xs => (!xs.contains x) && nodupNats xs

/-- One BFS expansion step over child edges: the children of the frontier
that have not been seen yet. -/
def bfsStep (tree : List TreeNode) (seen frontier : List Nat) : List Nat :=
  (frontier.flatMap (fun i =>
    match findTree tree i with
    | some t => t.children
    | none => [])).filter (fun c => !(seen.contains c) )

/-- Fuel-bounded BFS: returns (seen, frontier) after `fuel` layers. -/
def bfsLayers (tree : List TreeNode) :
    Nat → List Nat → List Nat → (List Nat × List Nat)
  | 0, seen, frontier => (seen, frontier)
  | fuel + 1, seen, frontier =>
      let next := bfsStep tree seen frontier
      bfsLayers tree fuel (seen ++ next) next

/-- Structural well-formedness of the subdivision tree. -/
def structuralOkT (hdr : IntHeader) (tree : List TreeNode) :
    Except String Unit := do
  guardE (!tree.isEmpty) "malformed-tree:empty"
  guardE (nodupNats (tree.map (·.id))) "malformed-tree:duplicate-id"
  -- every child reference exists and is strictly below its parent
  allE (fun t => allE (fun c =>
      guardE ((findTree tree c).isSome && decide (c < t.id))
        "malformed-tree:child-ref") t.children) tree
  -- root = maximal id = header root id, present, unreferenced
  match treeRootId tree with
  | none => .error "malformed-tree:empty"
  | some rid => do
      guardE (rid == hdr.root_id) "malformed-tree:root-id"
      guardE ((findTree tree hdr.root_id).isSome) "malformed-tree:missing-root"
      guardE (tree.all (fun t => !t.children.contains hdr.root_id))
        "malformed-tree:root-referenced"
      -- every non-root node is referenced exactly once (no sharing)
      let refs := tree.flatMap (·.children)
      guardE (nodupNats refs) "malformed-tree:shared-child"
      guardE (refs.length + 1 == tree.length) "malformed-tree:orphan"
      -- full reachability from the root (no orphan components)
      let (seen, _) := bfsLayers tree tree.length [hdr.root_id] [hdr.root_id]
      guardE (tree.all (fun t => seen.contains t.id)) "malformed-tree:orphan"
      -- engine depth policy: BFS exhausts within 60 layers below the root
      let (_, frontier) := bfsLayers tree (depthCap + 1) [hdr.root_id] [hdr.root_id]
      guardE frontier.isEmpty "depth-exhausted"
      -- engine budget policy (entry-check semantics: at most 60001 nodes)
      guardE (decide (tree.length ≤ budgetCap)) "budget-exhausted"

/-! ### Per-leaf pass -/

/-- Role table for a leaf kind: for each embedded certificate, in order,
`(k, full)` where `k` is the `DQiter` count the certificate's expression must
match and `full` selects the interval binding (`true`: exactly `[a, b]`;
`false`: must CONTAIN the exact midpoint `(a+b)/2`). -/
def roleSpecs (kind : String) : List (Nat × Bool) :=
  if kind = "range" then [(0, true)]
  else if kind = "taylor2" then [(0, true), (1, true), (2, true), (0, false)]
  else if kind = "taylor4" then
    [(0, true), (1, true), (2, true), (3, true), (4, true), (0, false), (2, false)]
  else []

/-- Check one embedded certificate against its role. -/
def checkEmbedded (hdr : IntHeader) (q : QExpr) (t : TreeNode)
    (spec : Nat × Bool) (c : EvalCert) : Except String Unit := do
  guardE (Cert.checkCert c.hdr c.nodes) "missing-premise:embedded-cert-rejected"
  guardE (qexprOf c.nodes == some (DQiter spec.1 q))
    "missing-premise:wrong-chain-expression"
  -- the integrand-level certificates also bind the artifact's expression
  -- commitment string (the checked sexp of the embedded certificate)
  guardE (spec.1 != 0 || c.hdr.expr_commitment == hdr.expr_commitment)
    "request-mismatch:expr"
  if spec.2 then do
    guardE (c.hdr.input_lo == t.a && c.hdr.input_hi == t.b)
      "missing-premise:input-mismatch"
  else do
    guardE (decide (c.hdr.input_lo ≤ (t.a + t.b) / 2) &&
            decide ((t.a + t.b) / 2 ≤ c.hdr.input_hi))
      "missing-premise:midpoint-not-contained"

/-- Check the role-ordered embedded certificates of a leaf. -/
def checkLeafCerts (hdr : IntHeader) (q : QExpr) (t : TreeNode) :
    List (Nat × Bool) → List EvalCert → Except String Unit
  | [], [] => .ok ()
  | spec :: specs, c :: cs => do
      checkEmbedded hdr q t spec c
      checkLeafCerts hdr q t specs cs
  | _, _ => .error "missing-premise:role-count"

/-- Exact-ℚ ideal conservativity of the leaf's claimed enclosure, per mode
(mirrors the shipped accepted forms including the range∩taylor intersect). -/
def checkLeafIdeal (t : TreeNode) : Except String Unit :=
  let h := t.b - t.a
  if t.kind == "range" then
    match t.certs with
    | [cF] => do
        guardE (decide (t.lo ≤ h * cF.hdr.output_lo)) "forged-enclosure:lower"
        guardE (decide (h * cF.hdr.output_hi ≤ t.hi)) "forged-enclosure:upper"
    | _ => .error "missing-premise:role-count"
  else if t.kind == "taylor2" then
    match t.certs with
    | [cF, _cF1, cF2, cFm] => do
        let rlo := h * cF.hdr.output_lo
        let rhi := h * cF.hdr.output_hi
        let tlo := h * cFm.hdr.output_lo + h ^ 3 / 24 * cF2.hdr.output_lo
        let thi := h * cFm.hdr.output_hi + h ^ 3 / 24 * cF2.hdr.output_hi
        guardE (decide (t.lo ≤ max rlo tlo)) "forged-enclosure:lower"
        guardE (decide (min rhi thi ≤ t.hi)) "forged-enclosure:upper"
    | _ => .error "missing-premise:role-count"
  else if t.kind == "taylor4" then
    match t.certs with
    | [cF, _cF1, _cF2, _cF3, cF4, cFm, cF2m] => do
        let rlo := h * cF.hdr.output_lo
        let rhi := h * cF.hdr.output_hi
        let tlo := h * cFm.hdr.output_lo + h ^ 3 / 24 * cF2m.hdr.output_lo
                     + h ^ 5 / 1920 * cF4.hdr.output_lo
        let thi := h * cFm.hdr.output_hi + h ^ 3 / 24 * cF2m.hdr.output_hi
                     + h ^ 5 / 1920 * cF4.hdr.output_hi
        guardE (decide (t.lo ≤ max rlo tlo)) "forged-enclosure:lower"
        guardE (decide (min rhi thi ≤ t.hi)) "forged-enclosure:upper"
    | _ => .error "missing-premise:role-count"
  else .error "unsupported-leaf-mode"

/-- The engine's per-leaf acceptance policy, in exact ℚ:
`width ≤ (9/10) · tol · (b−a) / span`. -/
def checkLeafPolicy (hdr : IntHeader) (t : TreeNode) : Except String Unit :=
  guardE (decide (t.hi - t.lo ≤
      9 / 10 * hdr.tol * (t.b - t.a) / (hdr.req_hi - hdr.req_lo)))
    "policy-violation:local-tolerance"

/-! ### Per-node pass -/

/-- The flat semantic check of one tree node. -/
def checkTreeNode (hdr : IntHeader) (q : QExpr) (tree : List TreeNode)
    (t : TreeNode) : Except String Unit := do
  guardE (decide (t.a < t.b)) "invalid-interval:domain"
  guardE (decide (t.lo ≤ t.hi)) "invalid-interval:enclosure"
  if t.kind == "split" then do
    guardE t.certs.isEmpty "malformed-tree:split-certs"
    match t.children with
    | [lid, rid] => do
        guardE (decide (lid < t.id) && decide (rid < t.id))
          "malformed-tree:child-order"
        match findTree tree lid, findTree tree rid with
        | some l, some r => do
            guardE (l.a == t.a) "child-partition-mismatch:left-a"
            guardE (l.b == r.a) "child-partition-mismatch:interior"
            guardE (r.b == t.b) "child-partition-mismatch:right-b"
            guardE (decide (t.lo ≤ l.lo + r.lo)) "forged-parent-sum:lower"
            guardE (decide (l.hi + r.hi ≤ t.hi)) "forged-parent-sum:upper"
        | _, _ => .error "malformed-tree:missing-child"
    | _ => .error "malformed-tree:split-arity"
  else do
    guardE (isLeafKind t.kind) "unsupported-leaf-mode"
    guardE (decide (kindRank t.kind ≤ hdr.degree)) "unsupported-leaf-mode:degree"
    guardE t.children.isEmpty "malformed-tree:leaf-children"
    checkLeafCerts hdr q t (roleSpecs t.kind) t.certs
    checkLeafIdeal t
    checkLeafPolicy hdr t

/-! ### The whole composition checker -/

/-- Header pins and request well-formedness. -/
def checkHeader (hdr : IntHeader) : Except String Unit := do
  guardE (hdr.schema_version == 1) "stale-identity:schema"
  guardE (hdr.model_const_version == Cert.pinnedModelConst) "stale-identity:model"
  guardE (hdr.checker_identity == shadowCheckerPin) "stale-identity:checker"
  guardE (hdr.status_class == shadowStatus) "stale-identity:status"
  guardE (decide (0 < hdr.tol)) "invalid-interval:tolerance"
  guardE (decide (hdr.req_lo < hdr.req_hi)) "invalid-interval:request"
  guardE (hdr.degree == 0 || hdr.degree == 2 || hdr.degree == 4)
    "request-mismatch:degree"

/-- The full shadow composition checker. -/
def checkIntCert (hdr : IntHeader) (tree : List TreeNode) :
    Except String Unit := do
  checkHeader hdr
  structuralOkT hdr tree
  match findTree tree hdr.root_id with
  | none => .error "malformed-tree:missing-root"
  | some root => do
      guardE (root.a == hdr.req_lo && root.b == hdr.req_hi)
        "request-mismatch:domain"
      match rootQExpr tree with
      | none => .error "missing-premise:no-root-integrand"
      | some q => do
          allE (checkTreeNode hdr q tree) tree
          guardE (decide (hdr.out_lo ≤ root.lo) && decide (root.hi ≤ hdr.out_hi))
            "released-interval-mismatch"
          guardE (decide (hdr.out_hi - hdr.out_lo ≤ hdr.tol)) "tolerance-unmet"

/-! ### Extraction lemmas (checker success ⇒ per-conjunct facts) -/

/-- Generic `Except` bind extraction: a successful sequence factors through a
successful first step. -/
theorem except_bind_ok {α β : Type} {x : Except String α}
    {f : α → Except String β} {u : β}
    (h : (x >>= f) = .ok u) : ∃ a, x = .ok a ∧ f a = .ok u := by
  cases x with
  | error e => exact absurd h (by simp [Bind.bind, Except.bind])
  | ok a => exact ⟨a, rfl, by simpa [Bind.bind, Except.bind] using h⟩

/-- A bare guard succeeding yields its condition. -/
theorem guard_ok {c : Bool} {r : String} {u : Unit}
    (h : guardE c r = .ok u) : c = true := by
  by_cases hc : c
  · exact hc
  · simp [guardE, hc] at h

/-- A guarded sequence succeeding yields the condition and the continuation. -/
theorem bind_guard_ok {α : Type} {c : Bool} {r : String}
    {f : Unit → Except String α} {u : α}
    (h : (guardE c r >>= f) = .ok u) : c = true ∧ f () = .ok u := by
  obtain ⟨a, hx, hf⟩ := except_bind_ok h
  exact ⟨guard_ok hx, hf⟩

/-- `allE` success yields the per-element fact. -/
theorem allE_ok {α : Type} {f : α → Except String Unit} :
    ∀ {l : List α}, allE f l = .ok () → ∀ x ∈ l, f x = .ok ()
  | [], _, x, hx => absurd hx (List.not_mem_nil)
  | y :: ys, h, x, hx => by
      unfold allE at h
      obtain ⟨a, hfy, hrest⟩ := except_bind_ok h
      rcases List.mem_cons.mp hx with rfl | hmem
      · exact hfy
      · exact allE_ok hrest x hmem

end JackalIv.Shadow
