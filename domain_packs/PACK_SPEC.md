# JACKAL Domain Pack Protocol v1

Status: additive pre-release contract for the Apple-Silicon macOS JACKAL
release train. This protocol does not reinterpret any historical v1.7.x
receipt, checker, registry, or runtime.

The v1 verifier refuses before repository access unless the executing host is
Darwin on arm64. Linux, Windows, and Intel/Rosetta execution are outside this
release contract.

## 1. Authority

A domain pack is a bounded capability declaration plus Anubis routing source.
The only authoritative computation and routing implementation is Anubis Safe
mode. Python may verify bytes, schemas, identities, parity, and receipts; it
may not choose a different operation, calculate a substitute answer, or raise
an assurance class.

`tools/domain_pack_verify.py` is deliberately a metadata, identity, and policy
verifier. Its accepted result explicitly records that Anubis was not executed
and assurance was not minted. Publication additionally requires the pinned
Anubis and independent-checker execution gates in section 7.

Every operation names an existing inference rule and evidence kind in the
pinned claim registry. A manifest value is only an assurance ceiling. It never
mints that assurance: the named independent checker and claim-bundle verifier
must still accept the operation's evidence.

## 2. Canonical route ABI

The v1 argv route is:

```text
pack-route <pack_id> <operation_id> <operation arguments...>
```

Pack and operation identifiers are exact, case-sensitive ASCII tokens. Unknown
identifiers, wrong arity, unsupported arguments, missing resources, and all
fallback requests refuse. A pack route must preserve the direct operation's
stdout bytes exactly unless a later protocol explicitly declares a migration.

The registered conformance routes are:

```text
jackal.core.exact         / core.exact.mod_pow.v1                   -> mod-pow
jackal.programming.source / programming.source.test_exists.v1       -> test-exists
jackal.programming.source / programming.source.claim_cites_test.v1  -> claim-cites-test
```

`domain_packs/core/core_pack.anb` and
`domain_packs/programming/programming_pack.anb` own those closed routing
choices and delegate to the existing Anubis handlers. A route source holds no
arithmetic and no file access of its own; it does not duplicate the operation
it routes to.

## 3. Manifest and registry

`PACK_SCHEMA.json` is the closed protocol vocabulary. Each manifest binds:

- pack identity, version, compatibility range, and request ABI;
- exact Anubis entry and routing source paths and SHA-256 digests;
- operation identifier, direct engine command, argument contract, response
  schema, checker identity, evidence kind, inference rule, and assurance
  ceiling;
- consequence ceiling, explicit refusal classes, forbidden fallback, resource
  budgets, and permanent nonclaims;
- a canonical self-digest over the manifest with its digest field omitted.

`registry_v1.json` binds the exact schema, this specification, the domain-pack
verifier itself, the historical claim inference registry, every pack manifest,
every Anubis route source, the JACKAL entry source, and the global operation
inventory. It also carries a canonical self-digest. The repository verifier rejects undeclared files under
`domain_packs/`, symlinks, non-regular files, duplicate JSON keys, unsafe
paths, digest drift, duplicate IDs, unknown schema fields, and over-budget
values. Metadata decoding has fixed byte, integer-digit, structure-depth, and
node ceilings; recursive inventory traversal has fixed entry, depth, and path
ceilings before it compares the exact declared tree.

The Git commit and release signature are the outer authority for a coherently
repinned registry. Self-digests detect accidental or partial mutation; they do
not authenticate a malicious author who can rewrite every file.

## 4. Assurance and consequence floors

An operation may name only a rule and evidence kind already present in the
pinned inference registry. `assurance_ceiling` must be in that registry's
mathematical axis. `consequence_ceiling` must be a registered consequence
class. The independent claim verifier still recomputes all axes, residuals,
policy floors, and the final rendering.

For `core.exact.mod_pow.v1`, the pack emits `jackal-exact-cert-v1` evidence and
uses the existing `evidence_admit / exact-cert` adapter. `exact` is therefore a
ceiling after independent replay, not a promise attached to raw stdout.

The v1 verifier carries a closed evidence-contract allowlist with three
entries. Each binds an evidence kind to exactly one response schema, exactly
one independent checker at an exact pinned digest, one assurance ceiling, and
one consequence bound:

| evidence kind | response schema | checker | assurance | consequence bound |
| --- | --- | --- | --- | --- |
| `exact-cert` | `jackal-exact-cert-v1` | `tools/exact_verify.py` | `exact` | `safety-critical` |
| `test-exists-cert` | `jackal-test-exists-cert-v1` | `tools/test_exists_verify.py` | `exact` | `informational` |
| `decision-cert` | `jackal-decision-cert-v1` | `tools/decision_verify.py` | `exact` | `decision-boundary` |

A pack cannot nominate a substitute checker, response schema,
registered-but-weaker inference rule, or newly repinned checker and inherit an
entry's assurance. Other evidence kinds present in the pinned inference
registry are not domain-pack-admissible until a protocol/verifier update adds
their complete trusted contract.

The consequence bound is enforced mechanically, not merely documented. An
operation's declared `consequence_ceiling` must be registered *and* must not
exceed its evidence kind's bound on the order
`informational < advisory < decision-boundary < safety-critical`. A manifest
that declares `consequence_ceiling: safety-critical` for a `test-exists-cert`
operation is refused with `v1 consequence ceiling exceeds the evidence-contract
bound`. The verifier additionally refuses if the pinned registry declares a
consequence class this order cannot rank, so the comparison is never made
against a partial order.

That bound is the whole point of the programming lane and is worth stating
plainly. "This test declaration exists in this file at this content hash" is a
byte-exact structural fact, so its assurance ceiling is genuinely `exact`. It
is nonetheless capped at `informational` in consequence, because a test
existing is never evidence that the code under test is correct. Assurance
describes how well a fact is established; consequence describes what may be
decided on it. Conflating the two is how a true structural fact gets rendered
as a correctness claim, and the allowlist exists to make that conflation
impossible rather than discouraged.

## 5. Resource and refusal contract

Every operation declares all v1 resource keys: request bytes, response bytes,
argument count, per-argument bytes, timeout, memory, syntax depth, and syntax
nodes. Zero, negative, missing, unknown, or protocol-exceeding values refuse.
The protocol's own v1 ceilings and mandatory nonclaims are compiled into the
verifier and cannot be raised or weakened by coherently repinning the schema.

`fallback.allowed` is always `false` in v1 and its reason is exactly
`fallback_forbidden`. A caller may submit a different request, but the router
never silently substitutes a weaker lane while preserving the original claim.

## 6. Compatibility and evolution

Pack changes are additive or versioned. Removing an operation, lowering a
resource bound in a compatibility-breaking way, changing output bytes,
changing an inference rule, or changing a checker requires a new pack version
and explicit migration evidence. Historical registry and receipt bytes remain
replayable under their original epoch.

## 7. Required gates

Publication requires:

1. schema, digest, inventory, and Anubis-authority verification;
2. Anubis checks for the entry source and every pack route source;
3. direct-versus-pack byte parity on a frozen positive corpus;
4. malformed, duplicate, fallback, resource, assurance, identity, and unknown
   operation refusals;
5. A-to-B-to-A restoration controls for registry, source, and route identity;
6. the existing JACKAL regression and release-evidence gates.

## 8. Permanent nonclaims

- A pack manifest is not proof of a theorem or correctness of an operation.
- A digest authenticates bytes only when an outer trusted commit or signature
  authenticates the digest.
- Exact mathematics does not establish truth, freshness, or provenance of
  caller-supplied real-world inputs.
- One conforming pack does not establish universal correctness or support for
  every STEM, programming, or decision request.
- Python orchestration and test agreement do not replace Anubis authority or
  the independent evidence checker.
- A programming-status pack establishes structure, never correctness. That a
  named declaration exists in a file at a stated content hash says nothing
  about whether the test runs, is collected by any runner, asserts anything, or
  covers the behaviour a surrounding document claims it covers. No output of
  such a pack may be rendered as evidence that the code under test is correct,
  and its consequence ceiling is capped at `informational` for exactly that
  reason.
- Resolving a citation is not validating it. `claim-cites-test` establishes
  that a cited symbol is declared in the cited file; a document may cite a real
  test that checks something entirely different, and no checker in this
  protocol can see that.
- A decision pack orders options by a declared, recomputable numeric criterion.
  It does not rank options by preference, goodness, or worth, and it does not
  establish that the declared criterion is the right one to decide on.
