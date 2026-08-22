#!/usr/bin/env python3
"""Contract and mutation gates for JACKAL agent profiles.

Positive cases (prefix ``test_positive_``) assert the shipped profiles verify
and mean what they claim. Refusal cases (prefix ``test_refusal_``) build an
A-to-B mutation in a temporary directory and require the verifier to fail closed
with a *named* reason. The real profile files are never mutated: every mutation
is a deep copy written under ``tempfile.mkdtemp``.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "tools" / "profile_verify.py"
PROFILE_DIR = Path("plugin") / "hermes" / "profiles"
SCHEMA_PATH = Path("plugin") / "hermes" / "schemas" / "jackal_agent_profile.schema.json"
TOOLS_PATH = Path("plugin") / "hermes" / "tools.json"
PACK_REGISTRY_PATH = Path("domain_packs") / "registry_v1.json"
PROFILE_IDS = ("core", "formal", "full")

EXPECTED_CORE_TOOLS = [
    "jackal_verify_receipt",
    "jackal_claim",
    "jackal_verify_bundle",
]

# The declared surface size is read from `tools.json`, never retyped here: this
# test's own history is the reason.  Hard-coding 34 in six places is what let
# four shipped pack operations sit unreachable behind a green suite.
EXPECTED_TOOL_COUNT = len(
    json.loads((ROOT / TOOLS_PATH).read_text(encoding="utf-8"))["tools"]
)


def load_verifier():
    spec = importlib.util.spec_from_file_location("profile_verify", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load profile verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = load_verifier()


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def declared_names() -> list[str]:
    document = read_json(ROOT / TOOLS_PATH)
    return [tool["name"] for tool in document["tools"]]


class ProfileFixture:
    """A throwaway copy of the profile surface, optionally mutated."""

    def __init__(self, mutate: Callable[[dict[str, dict[str, Any]]], None] | None = None,
                 reseal: bool = True):
        self.root = Path(tempfile.mkdtemp(prefix="jackal-profile-"))
        (self.root / PROFILE_DIR).mkdir(parents=True)
        (self.root / SCHEMA_PATH).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / SCHEMA_PATH, self.root / SCHEMA_PATH)
        shutil.copy2(ROOT / TOOLS_PATH, self.root / TOOLS_PATH)

        documents = {
            profile_id: copy.deepcopy(read_json(ROOT / PROFILE_DIR / f"{profile_id}.json"))
            for profile_id in PROFILE_IDS
        }
        if mutate is not None:
            mutate(documents)
            if reseal:
                for document in documents.values():
                    document["profile_digest_sha256"] = VERIFY.profile_digest(document)
        for profile_id, document in documents.items():
            (self.root / PROFILE_DIR / f"{profile_id}.json").write_text(
                json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class ProfilePositiveTest(unittest.TestCase):
    def test_positive_shipped_profiles_verify(self) -> None:
        result = VERIFY.verify_repository(ROOT)
        self.assertEqual(result["profile_verification"], "verified")
        self.assertEqual(result["tools_declared"], EXPECTED_TOOL_COUNT)
        self.assertEqual(result["profiles"]["core"]["tool_count"], 3)
        self.assertEqual(result["profiles"]["full"]["tool_count"], EXPECTED_TOOL_COUNT)
        # Non-vacuity: the combined release must carry the merged 38-tool
        # surface plus all three program-evidence tools.
        self.assertGreaterEqual(EXPECTED_TOOL_COUNT, 41)

    def test_positive_every_pack_operation_is_reachable_on_full(self) -> None:
        """The omission this test exists to make impossible.

        `domain_packs/registry_v1.json` shipped five operations across three
        packs while `plugin/hermes/tools.json` exposed none of them, so no agent
        could call any of them through the plugin and every gate stayed green.
        A pack operation that no profile exposes is unreachable, which is a
        silent omission rather than a refusal — exactly what `full`'s own
        description promises cannot happen.

        `core.exact.mod_pow.v1` is deliberately exempted BY NAME: it routes to
        the `mod-pow` engine command that `jackal_mod_pow` already exposes, so
        it is reachable without a second tool.  Every other operation must be
        named by some tool on `full`.
        """
        registry = read_json(ROOT / PACK_REGISTRY_PATH)
        declared = read_json(ROOT / TOOLS_PATH)["tools"]
        full = set(read_json(ROOT / PROFILE_DIR / "full.json")["tools"])
        # A tool claims an operation by naming it in its description; the
        # server binds the same id, and `tests/domain_pack_contract_test.py`
        # pins the ids themselves.
        blob = {
            tool["name"]: json.dumps(tool, sort_keys=True)
            for tool in declared if tool["name"] in full
        }
        exempt = {"core.exact.mod_pow.v1"}
        operations = [
            operation_id
            for pack in registry["packs"]
            for operation_id in pack["operation_ids"]
        ]
        self.assertGreaterEqual(len(operations), 5)
        for operation_id in operations:
            if operation_id in exempt:
                continue
            exposing = sorted(n for n, text in blob.items() if operation_id in text)
            self.assertEqual(
                len(exposing), 1,
                f"{operation_id} is exposed by {exposing} on the full profile; "
                "expected exactly one tool",
            )
        # And the exemption itself must stay honest: the operation it stands on
        # must still be in the registry, and its engine command still exposed.
        self.assertTrue(exempt <= set(operations))
        self.assertIn("jackal_mod_pow", full)

    def test_positive_unmutated_fixture_verifies(self) -> None:
        """Instrument check: without this, a refusal case could pass for the
        wrong reason (broken fixture) instead of the mutation under test."""
        fixture = ProfileFixture()
        try:
            result = VERIFY.verify_repository(fixture.root)
            self.assertEqual(result["profile_verification"], "verified")
            self.assertEqual(
                result["profiles"],
                VERIFY.verify_repository(ROOT)["profiles"],
            )
        finally:
            fixture.cleanup()

    def test_positive_cli_exits_zero_with_per_profile_lines(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(VERIFIER_PATH), "--root", str(ROOT)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for profile_id in PROFILE_IDS:
            self.assertIn(f"profile={profile_id} ", completed.stdout)
        self.assertEqual(completed.stdout.count(" OK"), 4)

    def test_positive_digests_are_reproducible_from_bytes(self) -> None:
        for profile_id in PROFILE_IDS:
            document = read_json(ROOT / PROFILE_DIR / f"{profile_id}.json")
            payload = {
                key: value
                for key, value in document.items()
                if key != "profile_digest_sha256"
            }
            expected = hashlib.sha256(canonical_bytes(payload)).hexdigest()
            self.assertEqual(document["profile_digest_sha256"], expected, profile_id)

    def test_positive_core_is_the_three_named_front_doors(self) -> None:
        core = read_json(ROOT / PROFILE_DIR / "core.json")
        self.assertEqual(core["tools"], EXPECTED_CORE_TOOLS)

    def test_positive_jackal_claim_still_declares_computing_step_ops(self) -> None:
        """Grounds the `core` description in tools.json rather than in prose.

        `jackal_claim` compiles caller-supplied step ops, several of which mint a
        fresh numeric value into the bundle. An earlier `core` description said the
        profile held "nothing that produces a fresh number", which is false while
        these ops exist. If they ever leave the tool, this test fails and the
        description must be revisited — which is the point of pinning it here
        instead of trusting the sentence.
        """
        declared = read_json(ROOT / TOOLS_PATH)["tools"]
        claim = next(t for t in declared if t["name"] == "jackal_claim")
        step_help = claim["arguments"]["request"]["help"]
        # Spelled exactly as tools.json spells them: the interval ops are declared
        # as one collapsed token, `interval_add/sub/mul/div`, not four names.
        for op in ("exact", "gaussian", "machine", "interval_add/sub/mul/div"):
            self.assertIn(op, step_help, op)

    def test_positive_core_description_states_the_mechanism_not_a_denial(self) -> None:
        """The `core` description must not deny that anything on it computes.

        The defensible claim is about which tools are claim/verification FRONT
        DOORS, and about the engine's policy router — not the caller — assigning
        assurance and consequence classes. The forbidden strings below are the
        specific false sentences, not bare keywords: a scan for a word like
        "number" would match the corrected text's own honest prose about minting
        fresh numeric evidence, which is the "grep matches its own explanation"
        trap. So this asserts an exact false claim is absent AND that the
        mechanism is named, and a bare denial cannot satisfy the second half.
        """
        description = read_json(ROOT / PROFILE_DIR / "core.json")["description"]
        for false_claim in (
            "nothing that produces a fresh number",
            "produces no fresh number",
            "no tool here computes",
        ):
            self.assertNotIn(false_claim, description)
        for mechanism in (
            "policy router",
            "rather than asserted by the caller",
            "explicit operator act",
        ):
            self.assertIn(mechanism, description, mechanism)
        # And the description must own up to the computing steps by name, so it
        # cannot be quietly narrowed back to a denial while keeping the mechanism
        # sentence.
        for op in ("exact", "gaussian", "machine", "interval_add"):
            self.assertIn(op, description, op)

    def test_positive_full_equals_tools_json_in_declaration_order(self) -> None:
        full = read_json(ROOT / PROFILE_DIR / "full.json")
        self.assertEqual(full["tools"], declared_names())

    def test_positive_profiles_are_nested_and_immutable(self) -> None:
        sets = {
            profile_id: set(read_json(ROOT / PROFILE_DIR / f"{profile_id}.json")["tools"])
            for profile_id in PROFILE_IDS
        }
        self.assertTrue(sets["core"] < sets["formal"])
        self.assertTrue(sets["formal"] < sets["full"])
        for profile_id in PROFILE_IDS:
            self.assertIs(
                read_json(ROOT / PROFILE_DIR / f"{profile_id}.json")["immutable"], True
            )

    def test_positive_verifier_never_rewrites_a_profile(self) -> None:
        before = {
            profile_id: (ROOT / PROFILE_DIR / f"{profile_id}.json").read_bytes()
            for profile_id in PROFILE_IDS
        }
        VERIFY.verify_repository(ROOT)
        for profile_id, raw in before.items():
            self.assertEqual(
                (ROOT / PROFILE_DIR / f"{profile_id}.json").read_bytes(), raw
            )

    def test_positive_schema_only_uses_implemented_keywords(self) -> None:
        """The instrument itself: an unimplemented keyword must be a refusal."""
        schema = read_json(ROOT / SCHEMA_PATH)
        allowed = VERIFY.SUPPORTED_KEYWORDS | VERIFY.ANNOTATION_KEYWORDS

        def keywords(node: object) -> set[str]:
            found: set[str] = set()
            if isinstance(node, dict):
                found |= set(node)
                for value in node.values():
                    found |= keywords(value)
            return found

        self.assertTrue(keywords(schema) - {"core", "formal", "full"} <= allowed | {
            "schema",
            "profile_id",
            "description",
            "tools",
            "immutable",
            "profile_digest_sha256",
        })
        with self.assertRaises(VERIFY.ProfileVerificationError) as caught:
            VERIFY.validate_against_schema(
                {"a": 1}, {"type": "object", "if": {"const": 1}}, "core"
            )
        self.assertEqual(caught.exception.reason, "schema-unsupported-keyword")


class ProfileRefusalTest(unittest.TestCase):
    """Every mutation here MUST be refused with its own named reason."""

    def _refuse(
        self,
        mutate: Callable[[dict[str, dict[str, Any]]], None],
        reason: str,
        profile: str | None = None,
        reseal: bool = True,
    ) -> VERIFY.ProfileVerificationError:
        fixture = ProfileFixture(mutate, reseal=reseal)
        try:
            with self.assertRaises(VERIFY.ProfileVerificationError) as caught:
                VERIFY.verify_repository(fixture.root)
            error = caught.exception
            self.assertEqual(error.reason, reason, str(error))
            if profile is not None:
                self.assertEqual(error.profile, profile, str(error))
            completed = subprocess.run(
                [sys.executable, str(VERIFIER_PATH), "--root", str(fixture.root)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout)
            self.assertIn(f"reason={reason}", completed.stderr)
            self.assertEqual(completed.stdout, "")
            return error
        finally:
            fixture.cleanup()

    def test_refusal_tampered_digest(self) -> None:
        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            digest = documents["core"]["profile_digest_sha256"]
            flipped = "0" if digest[-1] != "0" else "1"
            documents["core"]["profile_digest_sha256"] = digest[:-1] + flipped

        self._refuse(mutate, "digest-mismatch", profile="core", reseal=False)

    def test_refusal_digest_stale_after_description_edit(self) -> None:
        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            documents["formal"]["description"] += " Also totally formal, trust me."

        self._refuse(mutate, "digest-mismatch", profile="formal", reseal=False)

    def test_refusal_unknown_tool_name(self) -> None:
        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            documents["formal"]["tools"].append("jackal_prove_everything")

        self._refuse(mutate, "unknown-tool", profile="formal")

    def test_refusal_four_tool_core(self) -> None:
        """A real formal-lane tool, correctly ordered and nested: only arity is wrong."""

        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            documents["core"]["tools"].insert(0, "jackal_range_bound")

        error = self._refuse(mutate, "core-arity", profile="core")
        self.assertIn("exactly 3", str(error))

    def test_refusal_full_missing_one_tool(self) -> None:
        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            documents["full"]["tools"].remove("jackal_prime_cert")

        error = self._refuse(mutate, "full-incomplete", profile="full")
        self.assertIn("jackal_prime_cert", str(error))

    def test_refusal_unknown_top_level_key(self) -> None:
        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            documents["core"]["assurance_class"] = "formal-bounded"

        error = self._refuse(mutate, "schema-violation", profile="core")
        self.assertIn("rule=additionalProperties", str(error))

    def test_refusal_immutable_false(self) -> None:
        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            documents["full"]["immutable"] = False

        self._refuse(mutate, "immutable-false", profile="full")

    def test_refusal_core_not_subset_of_formal(self) -> None:
        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            documents["formal"]["tools"].remove("jackal_verify_receipt")

        error = self._refuse(mutate, "not-nested", profile="core")
        self.assertIn("jackal_verify_receipt", str(error))

    def test_refusal_formal_not_subset_of_full(self) -> None:
        """Drop a formal-lane tool from full: full-incomplete fires first, by design."""

        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            documents["full"]["tools"].remove("jackal_gaussian_integral")

        self._refuse(mutate, "full-incomplete", profile="full")

    def test_refusal_tools_out_of_declaration_order(self) -> None:
        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            tools = documents["formal"]["tools"]
            tools[0], tools[1] = tools[1], tools[0]

        self._refuse(mutate, "tool-order", profile="formal")

    def test_refusal_profile_id_mismatch(self) -> None:
        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            documents["formal"]["profile_id"] = "full"

        self._refuse(mutate, "profile-id-mismatch", profile="formal")

    def test_refusal_wrong_schema_identifier(self) -> None:
        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            documents["core"]["schema"] = "jackal-agent-profile-v2"

        error = self._refuse(mutate, "schema-violation", profile="core")
        self.assertIn("rule=const", str(error))

    def test_refusal_duplicate_tool_entry(self) -> None:
        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            documents["core"]["tools"].insert(0, "jackal_verify_receipt")

        error = self._refuse(mutate, "schema-violation", profile="core")
        self.assertIn("rule=uniqueItems", str(error))

    def test_refusal_missing_required_key(self) -> None:
        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            del documents["core"]["description"]

        error = self._refuse(mutate, "schema-violation", profile="core")
        self.assertIn("rule=required", str(error))

    def test_refusal_empty_tool_list(self) -> None:
        def mutate(documents: dict[str, dict[str, Any]]) -> None:
            documents["core"]["tools"] = []

        error = self._refuse(mutate, "schema-violation", profile="core")
        self.assertIn("rule=minItems", str(error))

    def test_refusal_missing_profile_file(self) -> None:
        fixture = ProfileFixture()
        try:
            (fixture.root / PROFILE_DIR / "formal.json").unlink()
            with self.assertRaises(VERIFY.ProfileVerificationError) as caught:
                VERIFY.verify_repository(fixture.root)
            self.assertEqual(caught.exception.reason, "missing-file")
        finally:
            fixture.cleanup()


class ProfileCaseCensusTest(unittest.TestCase):
    def test_case_census(self) -> None:
        positive = [
            name for name in dir(ProfilePositiveTest) if name.startswith("test_positive_")
        ]
        refusal = [
            name for name in dir(ProfileRefusalTest) if name.startswith("test_refusal_")
        ]
        print(
            f"\ncase_census positive={len(positive)} refusal={len(refusal)}",
            file=sys.stderr,
        )
        self.assertGreaterEqual(len(positive), 7)
        self.assertGreaterEqual(len(refusal), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
