/-
JackalIv/ShadowCertTypes.lean — SHADOW (research-shadow, NON-AUTHORITATIVE).

Structured schema of the v1.7 `bound_step` COMPOSITION artifact: one complete
accepted `integrate-bound` subdivision tree, with per-leaf embedded evaluation
certificates in the existing (proved) `jackal-eval-cert v2` schema.

Shape (mission §6.1 exact request binding):

  * `IntHeader` — request commitment (expression sexp + opaque source
    commitment), exact-ℚ integration endpoints and tolerance, the tree-wide
    `taylor_degree` policy bound, root id, and the RELEASED output interval
    (the engine's final `iv_out`-padded print).
  * `TreeNode` — one subdivision-tree node: exact-ℚ subinterval `[a, b]`,
    claimed enclosure `[lo, hi]` (the engine's UNPADDED per-node piece),
    kind ∈ {range, taylor2, taylor4, split}, children ids (splits), and the
    role-ordered embedded evaluation certificates (leaves).
  * `EvalCert` — an embedded `Cert.Header × List Cert.Node` certificate.

Leaf certificate roles, mirroring the shipped `bound_step` control flow
(jackal_calc.anb fn bound_step):

  range   : [F]                          — F  = ieval f over [a,b]
  taylor2 : [F, F1, F2, Fm]              — F1 = ieval (D f)  over [a,b]  (evaluability witness)
                                           F2 = ieval (D² f) over [a,b]  (remainder bounds)
                                           Fm = ieval f over the padded midpoint interval
  taylor4 : [F, F1, F2, F3, F4, Fm, F2m] — F3 evaluability witness, F4 remainder
                                           bounds, F2m = ieval (D² f) over the
                                           padded midpoint interval

The named TCB of the composition soundness theorem is `TreeTCB`: the
conjunction of the existing `Cert.ModelTCB` over every embedded certificate.
A `Prop` hypothesis — never a Lean axiom (vacuously provable when every
embedded certificate stays in the pure-ℚ fragment).

No `sorry`, no axiom, no `native_decide`, no `@[implemented_by]`.
-/
import JackalIv.CertSound
import JackalIv.ShadowQExpr

namespace JackalIv.Shadow

open JackalIv

/-! ### Pinned shadow identities -/

/-- Shadow checker/proof identity pin (mission §6.1 checker identity). -/
def shadowCheckerPin : String := "jackal-iv-bound-step-shadow-v1"

/-- Shadow status class — visibly non-public (mission §7). -/
def shadowStatus : String := "research-shadow"

/-- Engine budget mirror: `bound_step` refuses at entry when the running
node counter exceeds 60000, so an accepted tree has at most 60001 nodes. -/
def budgetCap : Nat := 60001

/-- Engine depth mirror: `bound_step` refuses when `depth > 60`. -/
def depthCap : Nat := 60

/-! ### Artifact structures -/

/-- An embedded evaluation certificate (existing proved schema v2). -/
structure EvalCert where
  hdr   : Cert.Header
  nodes : List Cert.Node
  deriving Repr, Inhabited, DecidableEq

/-- One subdivision-tree node. -/
structure TreeNode where
  id       : Nat
  kind     : String
  a        : ℚ
  b        : ℚ
  lo       : ℚ
  hi       : ℚ
  children : List Nat := []
  certs    : List EvalCert := []
  deriving Repr, Inhabited, DecidableEq

/-- Composition-artifact header. -/
structure IntHeader where
  schema_version      : Nat
  model_const_version : String
  checker_identity    : String
  producer_identity   : String
  status_class        : String
  expr_commitment     : String
  source_commitment   : String
  req_lo              : ℚ
  req_hi              : ℚ
  tol                 : ℚ
  degree              : Nat
  root_id             : Nat
  out_lo              : ℚ
  out_hi              : ℚ
  deriving Repr, Inhabited, DecidableEq

/-! ### Lookup helpers (mirror `Cert.findNode` discipline) -/

/-- Find the (first) tree node with the given id. -/
def findTree (tree : List TreeNode) (id : Nat) : Option TreeNode :=
  tree.find? (fun t => t.id == id)

/-- Root id: the maximal node id (under child-id < parent-id the root is the
unique maximal node). -/
def treeRootId (tree : List TreeNode) : Option Nat :=
  match tree with
  | [] => none
  | t :: rest => some (rest.foldl (fun acc m => max acc m.id) t.id)

/-! ### Leaf-mode tables -/

/-- Rank of a leaf kind against the tree-wide `taylor_degree` policy bound. -/
def kindRank (kind : String) : Nat :=
  if kind = "range" then 0
  else if kind = "taylor2" then 2
  else if kind = "taylor4" then 4
  else 5

/-- Number of embedded certificates a leaf kind requires (role-ordered). -/
def kindCertCount (kind : String) : Nat :=
  if kind = "range" then 1
  else if kind = "taylor2" then 4
  else if kind = "taylor4" then 7
  else 0

/-- Whether a kind string is a supported leaf mode. -/
def isLeafKind (kind : String) : Bool :=
  kind == "range" || kind == "taylor2" || kind == "taylor4"

/-! ### Root integrand extraction -/

/-- The ℚ-mirror integrand of the artifact: reconstructed from the FIRST
leaf's first (role-F) embedded certificate.  The checker separately verifies
that EVERY leaf's F/Fm certificates reconstruct to this same `QExpr` and that
every derivative-chain certificate reconstructs to the corresponding
`DQiter k` image. -/
def rootQExpr (tree : List TreeNode) : Option QExpr :=
  match tree.find? (fun t => isLeafKind t.kind) with
  | none => none
  | some t =>
      match t.certs with
      | [] => none
      | c :: _ => qexprOf c.nodes

/-! ### The named TCB -/

/-- The composition theorem's ONE named TCB: the existing `Cert.ModelTCB`
(libm + const-rounding facts) for every embedded evaluation certificate of
every tree node.  A `Prop` hypothesis, never an axiom. -/
def TreeTCB (tree : List TreeNode) : Prop :=
  ∀ t ∈ tree, ∀ c ∈ t.certs, Cert.ModelTCB c.hdr c.nodes

/-- Project a single certificate's `ModelTCB` out of `TreeTCB`. -/
theorem TreeTCB.cert {tree : List TreeNode} {t : TreeNode} {c : EvalCert}
    (h : TreeTCB tree) (ht : t ∈ tree) (hc : c ∈ t.certs) :
    Cert.ModelTCB c.hdr c.nodes :=
  h t ht c hc

end JackalIv.Shadow
