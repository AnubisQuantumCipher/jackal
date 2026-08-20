#!/usr/bin/env python3
"""Cross-pack non-laundering gates for the JACKAL domain-pack protocol.

This is the artifact the juggernaut plan names, and it exists because of a real
defect: an agent's own documentation once claimed a test verified every
polynomial moment through degree 23 while the test checked only degree 0. The
claim was grounded in a real file, was never fabricated, and was still false.

The structural version of that failure is *laundering*: taking a fact whose
assurance is genuinely `exact` and letting it be rendered at a consequence class
it cannot support. "This test exists" is byte-exact. It is never evidence that
the code under test is correct. So `test-exists-cert` carries assurance ceiling
`exact` and consequence bound `informational`, and `tools/domain_pack_verify.py`
refuses any manifest that declares a stronger consequence class -- even one that
is otherwise perfectly digest-coherent.

Every mutation here is applied to a temporary copy of the tree, with manifest and
registry self-digests re-derived so the tree stays coherent. That matters: an
incoherent tree is refused for a digest reason, and a test that accepted such a
refusal would prove nothing about the ceiling rule it claims to exercise. Two
guards keep this suite honest about that:

  * a non-vacuity control asserting the unmutated temporary tree ACCEPTS, so the
    refusals are attributable to the declared ceiling and not to the copy; and
  * an instrument check that flips only `consequence_bound` in the verifier's
    in-memory contract table and shows the identical laundering tree then
    ACCEPTS. Without it, "refused" could be a side effect of any other rule.

The real repository tree is never mutated.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "tools" / "domain_pack_verify.py"
COMPLETION_RECORD = ROOT / "docs" / "W3_W4_W6_W10_COMPLETION_RECORD.md"

PROGRAMMING_PACK = "jackal.programming.source"
DECISION_PACK = "jackal.decision.matrix"
CORE_PACK = "jackal.core.exact"

CONSEQUENCE_ORDER = ("informational", "advisory", "decision-boundary", "safety-critical")

# The ceiling matrix, transcribed from the completion record's table and checked
# against both the verifier's contract table and the record itself below. A
# hardcoded table is only trustworthy when something independent agrees with it,
# which is what `CeilingMatrixSourceTest` is for.
EXPECTED_BOUNDS = {
    "exact-cert": "safety-critical",
    "test-exists-cert": "informational",
    "decision-cert": "decision-boundary",
}
PACK_EVIDENCE_KIND = {
    CORE_PACK: "exact-cert",
    PROGRAMMING_PACK: "test-exists-cert",
    DECISION_PACK: "decision-cert",
}
# declared ceiling -> pack -> expected verdict. Derived from EXPECTED_BOUNDS by
# the ceiling rule (declare at or below the bound), and asserted against the
# record's transcribed table so a silent divergence cannot pass.
CEILING_MATRIX = {
    declared: {
        kind: "ACCEPTED"
        if CONSEQUENCE_ORDER.index(declared) <= CONSEQUENCE_ORDER.index(bound)
        else "REFUSED"
        for kind, bound in EXPECTED_BOUNDS.items()
    }
    for declared in CONSEQUENCE_ORDER
}

CEILING_REFUSAL = "v1 consequence ceiling exceeds the evidence-contract bound"


def load_verifier():
    spec = importlib.util.spec_from_file_location("domain_pack_verify", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load domain-pack verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_self_bound(path: Path, value: dict, digest_key: str) -> None:
    document = copy.deepcopy(value)
    document[digest_key] = sha256(
        canonical_bytes({key: item for key, item in document.items() if key != digest_key})
    )
    path.write_bytes(canonical_bytes(document) + b"\n")


class LaunderingTree(unittest.TestCase):
    """A disposable, digest-coherent copy of the domain-pack tree."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.verifier = load_verifier()

    def _referenced_checkers(self) -> set[str]:
        registry = json.loads(
            (ROOT / "domain_packs" / "registry_v1.json").read_text(encoding="utf-8")
        )
        paths: set[str] = set()
        for pack in registry["packs"]:
            manifest = json.loads((ROOT / pack["manifest_path"]).read_text(encoding="utf-8"))
            for operation in manifest["operations"]:
                paths.add(operation["checker"]["path"])
        if not paths:
            raise AssertionError("no manifest names a checker; the contract is vacuous")
        return paths

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="jackal-non-laundering-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "domain_packs", self.root / "domain_packs")
        (self.root / "release" / "claim").mkdir(parents=True)
        (self.root / "tools").mkdir()
        shutil.copy2(ROOT / "jackal_calc.anb", self.root / "jackal_calc.anb")
        for relative in sorted(self._referenced_checkers()):
            source = ROOT / relative
            if not source.is_file():
                raise AssertionError(f"manifest names checker {relative}, absent at {source}")
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        shutil.copy2(VERIFIER_PATH, self.root / "tools" / "domain_pack_verify.py")
        shutil.copy2(
            ROOT / "release" / "claim" / "inference_registry_v1.json",
            self.root / "release" / "claim" / "inference_registry_v1.json",
        )
        self.pristine = {
            path: path.read_bytes() for path in (self.root / "domain_packs").rglob("*.json")
        }

    def restore(self) -> None:
        for path, raw in self.pristine.items():
            path.write_bytes(raw)

    def repin_pack(self, pack_id: str, mutate) -> None:
        """Mutate one pack's manifest and re-derive every digest it feeds.

        Coherent repinning is the whole point. Without it the verifier refuses on
        `artifact digest mismatch` and the matrix below would be measuring the
        digest check, not the ceiling rule.
        """
        registry_path = self.root / "domain_packs" / "registry_v1.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        row = next(pack for pack in registry["packs"] if pack["pack_id"] == pack_id)
        manifest_path = self.root / row["manifest_path"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mutate(manifest)
        write_self_bound(manifest_path, manifest, "manifest_digest_sha256")
        row["manifest_sha256"] = sha256(manifest_path.read_bytes())
        write_self_bound(registry_path, registry, "registry_digest_sha256")

    def declare_consequence(self, pack_id: str, ceiling: str) -> None:
        def mutate(manifest: dict) -> None:
            for operation in manifest["operations"]:
                operation["consequence_ceiling"] = ceiling

        self.repin_pack(pack_id, mutate)

    def verify(self) -> dict:
        return self.verifier.verify_repository(self.root)

    def assertTreeAccepted(self) -> dict:
        result = self.verify()
        self.assertEqual(result["status"], "accepted")
        return result

    def assertTreeRefused(self, expected: str) -> str:
        with self.assertRaises(self.verifier.PackVerificationError) as caught:
            self.verify()
        message = str(caught.exception)
        self.assertIn(expected, message)
        return message


class NonVacuityControlTest(LaunderingTree):
    """Before any refusal is believed, the unmutated copy must ACCEPT."""

    def test_control_unmutated_temporary_tree_is_accepted(self) -> None:
        result = self.assertTreeAccepted()
        self.assertEqual(result["authority"], "anubis-safe-mode")
        self.assertEqual(result["assurance_status"], "NOT_MINTED")
        self.assertEqual(result["anubis_execution_status"], "NOT_EXECUTED")
        registry = json.loads(
            (ROOT / "domain_packs" / "registry_v1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            result["pack_ids"], sorted(pack["pack_id"] for pack in registry["packs"])
        )

    def test_control_coherent_repin_that_changes_nothing_is_accepted(self) -> None:
        """Repinning is not itself a refusal cause.

        Every matrix cell below rewrites the manifest and the registry. If that
        rewriting alone were enough to refuse, the whole matrix would read
        REFUSED for reasons that have nothing to do with consequence classes.
        """
        for pack_id in (CORE_PACK, PROGRAMMING_PACK, DECISION_PACK):
            with self.subTest(pack_id=pack_id):
                self.restore()
                self.repin_pack(pack_id, lambda manifest: None)
                self.assertTreeAccepted()

    def test_control_incoherent_repin_refuses_for_a_digest_reason(self) -> None:
        """The counter-control: prove the digest path and the ceiling path differ.

        Mutating the manifest without re-deriving the registry pin refuses with a
        digest message, NOT the ceiling message. So when a matrix cell reports the
        ceiling refusal, that is the rule which fired.
        """
        manifest_path = self.root / "domain_packs" / "programming" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for operation in manifest["operations"]:
            operation["consequence_ceiling"] = "safety-critical"
        manifest_path.write_bytes(canonical_bytes(manifest) + b"\n")
        message = self.assertTreeRefused("digest")
        self.assertNotIn(CEILING_REFUSAL, message)


class ProgrammingCannotBeLaunderedTest(LaunderingTree):
    """A structural programming fact may never be rendered above informational."""

    def test_test_exists_cert_refuses_advisory(self) -> None:
        self.declare_consequence(PROGRAMMING_PACK, "advisory")
        self.assertTreeRefused(CEILING_REFUSAL)

    def test_test_exists_cert_refuses_decision_boundary(self) -> None:
        self.declare_consequence(PROGRAMMING_PACK, "decision-boundary")
        self.assertTreeRefused(CEILING_REFUSAL)

    def test_test_exists_cert_refuses_safety_critical(self) -> None:
        self.declare_consequence(PROGRAMMING_PACK, "safety-critical")
        self.assertTreeRefused(CEILING_REFUSAL)

    def test_test_exists_cert_admits_informational(self) -> None:
        # The bound is an upper bound, not an equality. Without this the three
        # refusals above would be indistinguishable from a rule that refuses every
        # declared class.
        self.declare_consequence(PROGRAMMING_PACK, "informational")
        self.assertTreeAccepted()

    def test_the_class_immediately_above_the_bound_is_refused(self) -> None:
        # Off-by-one guard on the comparison itself: `advisory` is the adjacent
        # class, so a `>=`/`>` slip in the verifier shows up here first.
        bound = EXPECTED_BOUNDS["test-exists-cert"]
        adjacent = CONSEQUENCE_ORDER[CONSEQUENCE_ORDER.index(bound) + 1]
        self.assertEqual(adjacent, "advisory")
        self.declare_consequence(PROGRAMMING_PACK, adjacent)
        self.assertTreeRefused(CEILING_REFUSAL)

    def test_assurance_ceiling_stays_exact_while_consequence_is_capped(self) -> None:
        """The two axes are independent, and that is the point of the pack.

        A structural fact really is byte-exact. Capping its consequence class is
        not a hedge about the arithmetic; it is a statement about what the fact
        can be used to justify.
        """
        manifest = json.loads(
            (ROOT / "domain_packs" / "programming" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        for operation in manifest["operations"]:
            with self.subTest(operation=operation["operation_id"]):
                self.assertEqual(operation["assurance_ceiling"], "exact")
                self.assertEqual(operation["consequence_ceiling"], "informational")
                self.assertEqual(operation["evidence_kind"], "test-exists-cert")


class DecisionCannotReachSafetyCriticalTest(LaunderingTree):
    """A decision matrix may inform a decision boundary. It is not a safety case."""

    def test_decision_cert_refuses_safety_critical(self) -> None:
        self.declare_consequence(DECISION_PACK, "safety-critical")
        self.assertTreeRefused(CEILING_REFUSAL)

    def test_decision_cert_admits_informational(self) -> None:
        self.declare_consequence(DECISION_PACK, "informational")
        self.assertTreeAccepted()

    def test_decision_cert_admits_advisory(self) -> None:
        self.declare_consequence(DECISION_PACK, "advisory")
        self.assertTreeAccepted()

    def test_decision_cert_admits_decision_boundary(self) -> None:
        self.declare_consequence(DECISION_PACK, "decision-boundary")
        self.assertTreeAccepted()


class CeilingMatrixTest(LaunderingTree):
    """The full matrix, table-driven, one temporary tree per cell."""

    def test_full_ceiling_matrix(self) -> None:
        observed: dict[str, dict[str, str]] = {}
        for declared in CONSEQUENCE_ORDER:
            observed[declared] = {}
            for pack_id, kind in sorted(PACK_EVIDENCE_KIND.items()):
                with self.subTest(declared=declared, evidence_kind=kind):
                    self.restore()
                    self.declare_consequence(pack_id, declared)
                    expected = CEILING_MATRIX[declared][kind]
                    if expected == "ACCEPTED":
                        self.assertTreeAccepted()
                    else:
                        self.assertTreeRefused(CEILING_REFUSAL)
                    observed[declared][kind] = expected
        self.assertEqual(observed, CEILING_MATRIX)
        print("\nceiling_matrix " + json.dumps(observed, sort_keys=True), file=sys.stderr)

    def test_matrix_is_not_uniform_in_either_direction(self) -> None:
        """Guard against a matrix that is secretly all-ACCEPT or all-REFUSE.

        A table-driven test whose table has one distinct value everywhere is a
        table-driven tautology.
        """
        verdicts = {
            verdict for row in CEILING_MATRIX.values() for verdict in row.values()
        }
        self.assertEqual(verdicts, {"ACCEPTED", "REFUSED"})
        for kind in EXPECTED_BOUNDS:
            column = {CEILING_MATRIX[declared][kind] for declared in CONSEQUENCE_ORDER}
            with self.subTest(evidence_kind=kind):
                if kind == "exact-cert":
                    self.assertEqual(column, {"ACCEPTED"})
                else:
                    self.assertEqual(column, {"ACCEPTED", "REFUSED"})


class CeilingMatrixSourceTest(unittest.TestCase):
    """The transcribed matrix must agree with the code and with the record."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.verifier = load_verifier()

    def test_expected_bounds_match_the_verifier_contract_table(self) -> None:
        contracts = self.verifier.TRUSTED_V1_EVIDENCE_CONTRACTS
        self.assertEqual(set(contracts), set(EXPECTED_BOUNDS))
        for kind, bound in EXPECTED_BOUNDS.items():
            with self.subTest(evidence_kind=kind):
                self.assertEqual(contracts[kind]["consequence_bound"], bound)
                # Assurance is `exact` for all three; the consequence bound is
                # what distinguishes them. Asserting both keeps the distinction
                # from quietly collapsing.
                self.assertEqual(contracts[kind]["assurance_ceiling"], "exact")

    def test_consequence_order_matches_the_verifier(self) -> None:
        self.assertEqual(
            list(CONSEQUENCE_ORDER), list(self.verifier.PROTOCOL_V1_CONSEQUENCE_ORDER)
        )

    def test_transcribed_matrix_matches_the_completion_record_table(self) -> None:
        """Parse the record's own table and compare cell by cell.

        The plan requires the matrix in the completion record to be reproduced
        here. Reproducing it by retyping is how a document and its gate drift
        apart, so the document is parsed instead.
        """
        rows = self._record_matrix()
        self.assertEqual(
            sorted(rows), sorted(CONSEQUENCE_ORDER), "record rows are not the four classes"
        )
        for declared, cells in rows.items():
            for kind, verdict in cells.items():
                with self.subTest(declared=declared, evidence_kind=kind):
                    self.assertEqual(verdict, CEILING_MATRIX[declared][kind])

    def _record_matrix(self) -> dict[str, dict[str, str]]:
        text = COMPLETION_RECORD.read_text(encoding="utf-8")
        lines = text.splitlines()
        header_index = next(
            (
                index
                for index, line in enumerate(lines)
                if line.startswith("|") and "declared ceiling" in line
            ),
            None,
        )
        self.assertIsNotNone(
            header_index,
            f"{COMPLETION_RECORD.name} has no '| declared ceiling |' table header",
        )
        assert header_index is not None

        def cells(line: str) -> list[str]:
            return [cell.strip() for cell in line.strip().strip("|").split("|")]

        header = cells(lines[header_index])
        kinds: list[str] = []
        for column in header[1:]:
            match = re.search(r"`([a-z-]+-cert)`", column)
            self.assertIsNotNone(match, f"cannot read an evidence kind from {column!r}")
            assert match is not None
            kinds.append(match.group(1))
        self.assertTrue(kinds, "the record table declares no evidence-kind columns")

        rows: dict[str, dict[str, str]] = {}
        for line in lines[header_index + 2 :]:
            if not line.startswith("|"):
                break
            row = cells(line)
            declared = row[0].strip("`")
            if declared not in CONSEQUENCE_ORDER:
                break
            rows[declared] = {
                kind: verdict.strip() for kind, verdict in zip(kinds, row[1:])
            }
        return rows


class CeilingGuardIsLoadBearingTest(LaunderingTree):
    """Instrument check: prove the guard, not something adjacent, does the work."""

    def test_flipping_only_the_bound_admits_the_identical_laundering_tree(self) -> None:
        self.declare_consequence(PROGRAMMING_PACK, "safety-critical")
        self.assertTreeRefused(CEILING_REFUSAL)

        table = copy.deepcopy(self.verifier.TRUSTED_V1_EVIDENCE_CONTRACTS)
        table["test-exists-cert"]["consequence_bound"] = "safety-critical"
        # Only that one field differs. If anything else moved, the ACCEPT below
        # would be explained by the other change instead.
        original = self.verifier.TRUSTED_V1_EVIDENCE_CONTRACTS
        differences = [
            (kind, key)
            for kind, entry in table.items()
            for key, value in entry.items()
            if original[kind][key] != value
        ]
        self.assertEqual(differences, [("test-exists-cert", "consequence_bound")])

        with mock.patch.object(self.verifier, "TRUSTED_V1_EVIDENCE_CONTRACTS", table):
            result = self.verify()
        self.assertEqual(result["status"], "accepted")

        # And the flip must not be sticky: with the real table restored, the very
        # same untouched tree is refused again.
        self.assertTreeRefused(CEILING_REFUSAL)

    def test_flipping_the_decision_bound_admits_a_safety_critical_decision_pack(self) -> None:
        self.declare_consequence(DECISION_PACK, "safety-critical")
        self.assertTreeRefused(CEILING_REFUSAL)
        table = copy.deepcopy(self.verifier.TRUSTED_V1_EVIDENCE_CONTRACTS)
        table["decision-cert"]["consequence_bound"] = "safety-critical"
        with mock.patch.object(self.verifier, "TRUSTED_V1_EVIDENCE_CONTRACTS", table):
            self.assertEqual(self.verify()["status"], "accepted")
        self.assertTreeRefused(CEILING_REFUSAL)

    def test_lowering_a_bound_refuses_a_tree_that_is_accepted_today(self) -> None:
        """The mirror of the flip: tighten the bound and a live pack refuses.

        `decision-cert` declares `decision-boundary` in the shipped tree. Drop its
        bound to `advisory` and the unmutated tree must refuse -- so the rule reads
        the declared class against the bound in both directions.
        """
        self.assertTreeAccepted()
        table = copy.deepcopy(self.verifier.TRUSTED_V1_EVIDENCE_CONTRACTS)
        table["decision-cert"]["consequence_bound"] = "advisory"
        with mock.patch.object(self.verifier, "TRUSTED_V1_EVIDENCE_CONTRACTS", table):
            self.assertTreeRefused(CEILING_REFUSAL)


class CrossPackCaseCensusTest(unittest.TestCase):
    def test_case_census(self) -> None:
        groups = {
            "control": NonVacuityControlTest,
            "programming_launder": ProgrammingCannotBeLaunderedTest,
            "decision_launder": DecisionCannotReachSafetyCriticalTest,
            "matrix": CeilingMatrixTest,
            "matrix_source": CeilingMatrixSourceTest,
            "instrument": CeilingGuardIsLoadBearingTest,
        }
        counts = {
            name: len([n for n in dir(cls) if n.startswith("test_")])
            for name, cls in groups.items()
        }
        cells = sum(len(row) for row in CEILING_MATRIX.values())
        print(
            f"\ncross_pack_case_census {counts} matrix_cells={cells}",
            file=sys.stderr,
        )
        self.assertEqual(cells, len(CONSEQUENCE_ORDER) * len(EXPECTED_BOUNDS))
        self.assertGreaterEqual(counts["control"], 3)
        self.assertGreaterEqual(counts["programming_launder"], 5)
        self.assertGreaterEqual(counts["decision_launder"], 4)
        self.assertGreaterEqual(counts["instrument"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
