#!/usr/bin/env python3
"""Engine-level gates for the `jackal.decision.matrix` domain pack.

Same shape as `tests/programming_pack_test.py`: the pinned Anubis engine runs as
a subprocess, and every certificate it emits is put through the real independent
checker (`tools/decision_verify.py`) as a second subprocess. Case data comes from
the frozen corpus at `tests/corpus/decision_corpus_v1.json`, so the expectations
are recorded observations rather than assertions invented here.

The boundary these gates defend
-------------------------------
`decision-rank` orders options by a declared, recomputable integer quantity. Its
assurance ceiling is `exact` because the selection and the margin are arithmetic
on the caller's own numbers; its consequence ceiling stops at
`decision-boundary`, never `safety-critical`. Two refusals carry the weight:

  * `decision-value-judgment` -- ranking on goodness, worth, or preference is not
    a measurable quantity, and rendering one as a mathematical selection is the
    laundering this pack refuses.
  * `decision-margin-zero` -- a tie at the top is a coin flip, and a coin flip
    wearing a certificate is worse than no certificate.

What these gates do NOT establish
---------------------------------
That the declared criterion is the right one to optimise, that the declared
values are true or measured rather than guessed, or that the selected option is
preferable. Those are permanent nonclaims of the pack. One of them is a real,
open gap in the current implementation, and
`test_known_gap_substring_blocklist_misses_optimal` makes it visible instead of
leaving it as folklore.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_generator():
    path = ROOT / "tests" / "corpus" / "generate_pack_corpus.py"
    spec = importlib.util.spec_from_file_location("jackal_pack_corpus", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = _load_generator()


class DecisionPackCase(unittest.TestCase):
    CORPUS = "decision"

    @classmethod
    def setUpClass(cls) -> None:
        if not GEN.ANUBIS.is_file():
            raise unittest.SkipTest(f"pinned Anubis compiler unavailable at {GEN.ANUBIS}")
        cls.engine = GEN.Engine.shared()
        cls.corpus = GEN.load_corpus(cls.CORPUS)
        cls.rows = GEN.cases_by_id(cls.corpus)

    def row(self, case_id: str) -> dict:
        self.assertIn(case_id, self.rows, f"{case_id} is not in the frozen corpus")
        return self.rows[case_id]

    def replay(self, case_id: str):
        row = self.row(case_id)
        argv = list(row["argv"])
        if row["invocation"] == "pack-route":
            observed = self.engine.route(
                row.get("route_pack_id", self.corpus["pack_id"]),
                row.get("route_operation_id", row["operation_id"]),
                *argv,
            )
        else:
            observed = self.engine.run(row["engine_command"], *argv)

        self.assertEqual(observed.returncode, row["engine"]["returncode"])
        self.assertEqual(observed.refusal_class, row["engine"]["refusal_class"])
        self.assertEqual(observed.stdout, row["engine"]["stdout"])

        if row["checker"] is None:
            return observed, None

        certificate = observed.certificate(GEN.DECISION_PREFIX)
        if "tamper" in row:
            certificate = GEN.apply_tamper(certificate, GEN.DECISION_PREFIX, row["tamper"])
        self.assertEqual(certificate, row["certificate"])
        verdict = GEN.check_decision(certificate)
        self.assertEqual(verdict.summary, row["checker"]["verdict"], verdict.line)
        self.assertEqual(verdict.returncode, row["checker"]["returncode"])
        return observed, verdict

    def assertEngineRefusal(self, case_id: str, expected: str) -> None:
        observed, verdict = self.replay(case_id)
        self.assertNotEqual(observed.returncode, 0)
        self.assertEqual(observed.refusal_class, expected)
        self.assertIsNone(verdict)
        self.assertNotIn(GEN.DECISION_PREFIX, observed.stdout)

    def assertCheckerRefusal(self, case_id: str, expected: str) -> None:
        observed, verdict = self.replay(case_id)
        self.assertEqual(observed.returncode, 0, "the engine must mint this certificate")
        assert verdict is not None
        self.assertEqual(verdict.reason_class, expected, verdict.line)
        self.assertEqual(verdict.returncode, 2)

    def claim(self, certificate: str) -> dict:
        return json.loads(certificate[len(GEN.DECISION_PREFIX) :])["claim"]


class DecisionHarnessTest(DecisionPackCase):
    def test_harness_drives_the_pinned_compiler(self) -> None:
        self.assertEqual(self.engine.anubis_pin, GEN.ANUBIS.name)
        self.assertEqual(
            self.engine.engine_source_sha256,
            hashlib.sha256((ROOT / "jackal_calc.anb").read_bytes()).hexdigest(),
        )
        self.assertIn("exact-cert=", self.engine.probe_stdout)

    def test_fast_path_is_byte_identical_to_the_jackal_launcher(self) -> None:
        if self.engine.mode != "prebuilt-native":
            self.skipTest("harness is already using the launcher for every call")
        argv = list(self.row("positive_decision_min")["argv"])
        fast = self.engine.run("decision-rank", *argv)
        launched = self.engine.run_via_launcher("decision-rank", *argv)
        self.assertEqual(launched.returncode, 0, launched.stderr[-800:])
        self.assertEqual(launched.stdout, fast.stdout)

    def test_corpus_checker_identity_still_matches_disk(self) -> None:
        self.assertEqual(
            GEN.sha256_file(self.corpus["checker"]["path"]),
            self.corpus["checker"]["sha256"],
        )

    def test_corpus_aggregate_digest_is_self_consistent(self) -> None:
        self.assertEqual(self.corpus[GEN.DIGEST_KEY], GEN.corpus_digest(self.corpus))

    def test_corpus_covers_all_three_case_classes(self) -> None:
        counts = self.corpus["case_counts"]
        self.assertGreaterEqual(counts["positive"], 4)
        self.assertGreaterEqual(counts["refusal"], 7)
        self.assertGreaterEqual(counts["poison"], 6)

    def test_checker_blocklist_is_byte_identical_to_the_engine_list(self) -> None:
        """The checker's value-judgment list must not drift from the engine's.

        If the two lists diverge, the engine and its independent checker disagree
        about what is admissible, and one of them is minting or refusing on the
        wrong basis. The engine's list lives in `jackal_calc.anb`; the checker
        mirrors it in `VALUE_JUDGMENT_WORDS`. Every mirrored word must still be
        refused by the engine, which is the property that actually matters.
        """
        checker = GEN._load_module("jackal_decision_verify", GEN.DECISION_CHECKER)
        self.assertGreaterEqual(len(checker.VALUE_JUDGMENT_WORDS), 20)
        for word in checker.VALUE_JUDGMENT_WORDS:
            with self.subTest(word=word):
                observed = self.engine.run(
                    "decision-rank", "d_drift", f"{word}_metric", "max", "a", "1", "b", "2"
                )
                self.assertEqual(
                    observed.refusal_class,
                    "decision-value-judgment",
                    f"the checker refuses {word!r} but the engine does not",
                )


class DecisionPositiveTest(DecisionPackCase):
    def test_positive_decision_max_is_accepted(self) -> None:
        observed, verdict = self.replay("positive_decision_max")
        self.assertIn("status=exact selected=beta margin=150", observed.stdout)
        self.assertIn("consequence=decision-boundary", observed.stdout)
        assert verdict is not None
        self.assertEqual(verdict.summary, "ACCEPT")
        claim = self.claim(observed.certificate(GEN.DECISION_PREFIX))
        self.assertEqual(claim["sense"], "max")
        self.assertEqual(claim["selected"], "beta")
        self.assertEqual(claim["runner_up"], "gamma")
        self.assertEqual(claim["margin"], "150")
        self.assertIn("this is NOT a claim it is the right one", verdict.stdout)

    def test_positive_decision_min_is_accepted(self) -> None:
        observed, verdict = self.replay("positive_decision_min")
        self.assertIn("status=exact selected=beta margin=30", observed.stdout)
        assert verdict is not None
        self.assertEqual(verdict.summary, "ACCEPT")
        claim = self.claim(observed.certificate(GEN.DECISION_PREFIX))
        self.assertEqual(claim["sense"], "min")
        self.assertEqual(claim["selected"], "beta")
        self.assertEqual(claim["margin"], "30")

    def test_positive_decision_six_options_upper_bound_is_accepted(self) -> None:
        observed, verdict = self.replay("positive_decision_six_options_upper_bound")
        assert verdict is not None
        self.assertEqual(verdict.summary, "ACCEPT")
        self.assertEqual(len(self.claim(observed.certificate(GEN.DECISION_PREFIX))["options"]), 6)

    def test_positive_decision_negative_values_are_accepted(self) -> None:
        observed, verdict = self.replay("positive_decision_negative_values")
        assert verdict is not None
        self.assertEqual(verdict.summary, "ACCEPT")
        claim = self.claim(observed.certificate(GEN.DECISION_PREFIX))
        self.assertEqual(claim["selected"], "beta")
        self.assertEqual(claim["margin"], "33")

    def test_positive_decision_negative_zero_is_normalised(self) -> None:
        observed, verdict = self.replay("positive_decision_negative_zero_is_normalised")
        assert verdict is not None
        self.assertEqual(verdict.summary, "ACCEPT")
        # The checker refuses `-0` as a non-canonical integer. The engine never
        # emits it, so that refusal is unreachable through the engine -- recorded
        # so nobody later mistakes it for a live guard on this path.
        claim = self.claim(observed.certificate(GEN.DECISION_PREFIX))
        self.assertEqual(claim["options"][0]["value"], "0")


class DecisionRouteParityTest(DecisionPackCase):
    def _assert_parity(self, case_id: str) -> None:
        row = self.row(case_id)
        argv = list(row["argv"])
        direct = self.engine.run("decision-rank", *argv)
        routed = self.engine.route(self.corpus["pack_id"], GEN.OP_DECISION_RANK, *argv)
        self.assertEqual(direct.returncode, 0, direct.stderr[-800:])
        self.assertEqual(routed.returncode, 0, routed.stderr[-800:])
        self.assertEqual(routed.stdout, direct.stdout)
        self.assertIn(GEN.DECISION_PREFIX, routed.stdout)
        self.assertTrue(row["route_parity"])

    def test_route_parity_decision_rank_max(self) -> None:
        self._assert_parity("positive_decision_max")

    def test_route_parity_decision_rank_min(self) -> None:
        self._assert_parity("positive_decision_min")

    def test_route_parity_holds_for_every_certificate_bearing_case(self) -> None:
        for case_id, row in sorted(self.rows.items()):
            if row["checker"] is None:
                continue
            with self.subTest(case=case_id):
                self.assertIs(row["route_parity"], True)


class DecisionEngineRefusalTest(DecisionPackCase):
    def test_refusal_criterion_is_a_value_judgment(self) -> None:
        self.assertEngineRefusal(
            "refusal_criterion_is_a_value_judgment", "decision-value-judgment"
        )

    def test_refusal_top_two_tie(self) -> None:
        self.assertEngineRefusal("refusal_top_two_tie", "decision-margin-zero")

    def test_refusal_duplicate_label(self) -> None:
        self.assertEngineRefusal("refusal_duplicate_label", "decision-duplicate-label")

    def test_refusal_sense_unknown(self) -> None:
        self.assertEngineRefusal("refusal_sense_unknown", "decision-sense-unknown")

    def test_refusal_odd_label_value_pairing(self) -> None:
        self.assertEngineRefusal("refusal_odd_label_value_pairing", "pack-request-arity")

    def test_refusal_fewer_than_two_options(self) -> None:
        self.assertEngineRefusal("refusal_fewer_than_two_options", "pack-request-arity")

    def test_refusal_more_than_six_options(self) -> None:
        self.assertEngineRefusal("refusal_more_than_six_options", "pack-request-arity")

    def test_refusal_route_unknown_operation_id_does_not_fall_back(self) -> None:
        observed, _ = self.replay("refusal_route_unknown_operation_id")
        self.assertEqual(observed.refusal_class, "pack-operation-unknown")
        self.assertIn("no fallback is permitted", observed.refusal_detail or "")


class DecisionCheckerRefusalTest(DecisionPackCase):
    def test_poison_selected_relabelled(self) -> None:
        self.assertCheckerRefusal("poison_selected_relabelled", "cert-selection-mismatch")

    def test_poison_selected_and_runner_up_collapsed(self) -> None:
        self.assertCheckerRefusal(
            "poison_selected_and_runner_up_collapsed", "cert-runner-up-is-selected"
        )

    def test_poison_runner_up_relabelled(self) -> None:
        self.assertCheckerRefusal("poison_runner_up_relabelled", "cert-runner-up-mismatch")

    def test_poison_margin_inflated(self) -> None:
        self.assertCheckerRefusal("poison_margin_inflated", "cert-margin-mismatch")

    def test_poison_margin_forced_to_zero(self) -> None:
        self.assertCheckerRefusal(
            "poison_margin_forced_to_zero_by_flattening_values", "cert-margin-zero"
        )

    def test_poison_criterion_rewritten_to_a_value_judgment(self) -> None:
        self.assertCheckerRefusal(
            "poison_criterion_rewritten_to_a_value_judgment", "cert-value-judgment"
        )

    def test_poison_malformed_envelope_missing_witness(self) -> None:
        self.assertCheckerRefusal(
            "poison_malformed_envelope_missing_witness", "cert-envelope-keys"
        )

    def test_poison_value_wider_than_the_checker_admits(self) -> None:
        """A documented engine/checker divergence, not a soundness hole.

        The engine admits a 65-digit magnitude that the checker's canonical
        integer shape rejects. The checker is the stricter of the two, so the
        divergence cannot admit anything it should refuse -- it can only refuse a
        certificate the engine was willing to mint. Recorded here so the
        asymmetry is a tested fact rather than folklore.
        """
        self.assertCheckerRefusal(
            "poison_value_wider_than_the_checker_admits", "cert-field-shape"
        )

    def test_control_untampered_certificate_is_still_accepted(self) -> None:
        # Non-vacuity control for the tampering column: the same minting call,
        # the same checker, no mutation -- ACCEPT. So every refusal above is
        # attributable to its mutation and not to the harness.
        row = self.row("poison_selected_relabelled")
        observed = self.engine.run("decision-rank", *row["argv"])
        self.assertEqual(observed.returncode, 0, observed.stderr[-800:])
        verdict = GEN.check_decision(observed.certificate(GEN.DECISION_PREFIX))
        self.assertEqual(verdict.summary, "ACCEPT", verdict.line)


class DecisionKnownGapTest(DecisionPackCase):
    """The v1 lane's open gap, asserted as a gap.

    A test that pins current behaviour is not an endorsement of it. These exist
    so that the next person reads the limitation from a test rather than
    rediscovering it in production.

    The gap below is now CLOSED in a second operation, `decision.matrix.rank.v2`
    (see `DecisionV2GapClosedTest`), and deliberately still OPEN in v1. v1 is a
    shipped, versioned operation with a frozen corpus; narrowing its accepted
    input surface would break its callers, so it is retained unchanged and v2 is
    the closed lane. Every assertion in this class is byte-for-byte the one that
    was here before v2 landed.
    """

    def test_known_gap_substring_blocklist_misses_optimal(self) -> None:
        """`optimal` and `b3st` pass a substring blocklist. They should not.

        `require_measurable_criterion` refuses a criterion whose lowercased text
        contains any of a fixed word list (`better`, `best`, `worth`, ...). That
        catches the obvious spellings and nothing else. A criterion named
        `optimal_score` is exactly as much a value judgment as `best_score`, and
        `b3st` is the same word with a digit in it, yet both are ACCEPTED
        end-to-end by the v1 engine command AND by the independent checker.

        This test asserts the ACCEPT deliberately. It documents the gap in v1; it
        does not bless it, and v1 is retained unchanged only for compatibility
        with its existing callers.

        Closing it needed a different mechanism, not a longer word list: a
        blocklist over free text can always be spelled around. That mechanism is
        `decision.matrix.rank.v2`, which requires a *declared unit* from the
        closed vocabulary of `release/claim/unit_registry_v1.json`, so
        admissibility is decided by what the number measures rather than by which
        letters the caller chose. `DecisionV2GapClosedTest` runs these same four
        criteria through v2 and asserts each is refused by a named class. Through
        v1, as below, they still rank.
        """
        for criterion in ("optimal_score", "ideal_score", "b3st", "most_elegant"):
            with self.subTest(criterion=criterion):
                observed = self.engine.run(
                    "decision-rank", "d_gap", criterion, "max", "alpha", "1", "beta", "2"
                )
                self.assertEqual(
                    observed.returncode,
                    0,
                    f"{criterion} is now refused; the gap has closed and this "
                    f"test must be rewritten as a refusal case",
                )
                verdict = GEN.check_decision(observed.certificate(GEN.DECISION_PREFIX))
                self.assertEqual(
                    verdict.summary,
                    "ACCEPT",
                    f"{criterion} is now refused by the checker but not the engine, "
                    f"which is a divergence, not a fix",
                )

    def test_known_gap_blocklist_does_catch_the_obvious_spellings(self) -> None:
        # The paired control: the blocklist is not useless, it is only shallow.
        # Without this, the gap test above could be read as "no criterion is ever
        # refused", which is false.
        for criterion in ("best_score", "better_value", "most_worthy", "ought_to_win"):
            with self.subTest(criterion=criterion):
                observed = self.engine.run(
                    "decision-rank", "d_gap", criterion, "max", "alpha", "1", "beta", "2"
                )
                self.assertEqual(observed.refusal_class, "decision-value-judgment")


class DecisionV2PositiveTest(DecisionPackCase):
    """The v2 lane accepts, and mints a certificate the checker verifies.

    This class is the discrimination control for every v2 refusal below. A suite
    made only of refusals cannot tell "correctly refuses an inadmissible unit"
    from "the operation does not exist in this binary": both refuse. These tests
    fail outright against an engine without `decision-rank-v2`, and they assert
    the `unit` field is carried all the way into the certificate, which no other
    operation in the repository emits.
    """

    def test_positive_v2_declared_unit_min_is_accepted(self) -> None:
        observed, verdict = self.replay("positive_v2_declared_unit_min")
        self.assertIn("status=exact selected=beta margin=30 unit=ms", observed.stdout)
        self.assertIn("a-declared-unit-is-not-a-measurement", observed.stdout)
        assert verdict is not None
        self.assertEqual(verdict.summary, "ACCEPT")
        certificate = observed.certificate(GEN.DECISION_PREFIX)
        payload = json.loads(certificate[len(GEN.DECISION_PREFIX) :])
        self.assertEqual(payload["schema"], "jackal-decision-cert-v2")
        self.assertEqual(payload["kind"], "decision-rank-v2")
        self.assertEqual(payload["claim"]["unit"], "ms")
        self.assertEqual(payload["claim"]["selected"], "beta")
        self.assertEqual(payload["claim"]["margin"], "30")
        self.assertIn("admitted from the closed vocabulary", verdict.stdout)
        self.assertIn("a declared unit is a declaration, not a measurement", verdict.stdout)

    def test_positive_v2_declared_unit_max_rate_is_accepted(self) -> None:
        observed, verdict = self.replay("positive_v2_declared_unit_max_rate")
        assert verdict is not None
        self.assertEqual(verdict.summary, "ACCEPT")
        claim = self.claim(observed.certificate(GEN.DECISION_PREFIX))
        self.assertEqual(claim["unit"], "Hz")
        self.assertEqual(claim["selected"], "beta")
        self.assertEqual(claim["margin"], "150")

    def test_positive_v2_ratio_unit_percent_is_accepted(self) -> None:
        observed, verdict = self.replay("positive_v2_ratio_unit_percent")
        assert verdict is not None
        self.assertEqual(verdict.summary, "ACCEPT")
        self.assertEqual(self.claim(observed.certificate(GEN.DECISION_PREFIX))["unit"], "percent")

    def test_positive_v2_six_options_upper_bound_is_accepted(self) -> None:
        observed, verdict = self.replay("positive_v2_six_options_upper_bound")
        assert verdict is not None
        self.assertEqual(verdict.summary, "ACCEPT")
        claim = self.claim(observed.certificate(GEN.DECISION_PREFIX))
        self.assertEqual(len(claim["options"]), 6)
        self.assertEqual(claim["unit"], "kWh")

    def test_v2_route_parity_is_byte_identical_to_the_direct_command(self) -> None:
        for case_id in (
            "positive_v2_declared_unit_min",
            "positive_v2_six_options_upper_bound",
        ):
            with self.subTest(case=case_id):
                row = self.row(case_id)
                argv = list(row["argv"])
                direct = self.engine.run("decision-rank-v2", *argv)
                routed = self.engine.route(
                    self.corpus["pack_id"], GEN.OP_DECISION_RANK_V2, *argv
                )
                self.assertEqual(direct.returncode, 0, direct.stderr[-800:])
                self.assertEqual(routed.returncode, 0, routed.stderr[-800:])
                self.assertEqual(routed.stdout, direct.stdout)
                self.assertIn("jackal-decision-cert-v2", routed.stdout)
                self.assertTrue(row["route_parity"])

    def test_v2_selection_agrees_with_v1_on_the_same_numbers(self) -> None:
        """Differential gate against the two lanes drifting apart.

        `cmd_decision_rank_v2` is a separate implementation from
        `cmd_decision_rank`, because v1 is frozen and must not be edited. The
        price of that is two copies of the same argmax/argmin, so this runs both
        over identical numbers and compares what they selected. If someone later
        fixes a tie-break or a margin in one and not the other, this fails.
        """
        cases = [
            ("max", ["alpha", "120", "beta", "400", "gamma", "250"]),
            ("min", ["alpha", "120", "beta", "400", "gamma", "250"]),
            ("max", ["alpha", "-40", "beta", "-7"]),
            ("min", ["alpha", "-40", "beta", "-7"]),
            ("max", ["a", "1", "b", "2", "c", "3", "d", "4", "e", "5", "f", "6"]),
            ("min", ["a", "0", "b", "-9", "c", "9"]),
        ]
        for sense, options in cases:
            with self.subTest(sense=sense, options=tuple(options)):
                v1 = self.engine.run("decision-rank", "d_diff", "latency_ms", sense, *options)
                v2 = self.engine.run(
                    "decision-rank-v2", "d_diff", "latency_ms", "ms", sense, *options
                )
                self.assertEqual(v1.returncode, 0, v1.stderr[-400:])
                self.assertEqual(v2.returncode, 0, v2.stderr[-400:])
                one = self.claim(v1.certificate(GEN.DECISION_PREFIX))
                two = self.claim(v2.certificate(GEN.DECISION_PREFIX))
                self.assertEqual(
                    {key: one[key] for key in ("selected", "runner_up", "margin", "options")},
                    {key: two[key] for key in ("selected", "runner_up", "margin", "options")},
                )


class DecisionV2EngineRefusalTest(DecisionPackCase):
    """Every v2 refusal, asserted by its specific named class.

    `assertEngineRefusal` compares `observed.refusal_class` to an exact string
    parsed out of the engine's `ANUBIS_PANIC` line. A bare nonzero-exit check
    would not distinguish a unit-vocabulary refusal from `pack-operation-unknown`
    raised by an engine where v2 does not exist at all.
    """

    def test_refusal_v2_unit_outside_the_closed_vocabulary(self) -> None:
        self.assertEngineRefusal(
            "refusal_v2_unit_outside_the_closed_vocabulary", "decision-unit-unknown"
        )

    def test_refusal_v2_unit_declared_empty(self) -> None:
        self.assertEngineRefusal("refusal_v2_unit_declared_empty", "decision-unit-missing")

    def test_refusal_v2_unit_omitted_entirely(self) -> None:
        self.assertEngineRefusal("refusal_v2_unit_omitted_entirely", "pack-request-arity")

    def test_refusal_v2_route_arity_rejects_a_missing_unit(self) -> None:
        self.assertEngineRefusal(
            "refusal_v2_route_arity_rejects_a_missing_unit", "pack-request-arity"
        )

    def test_refusal_v2_leetspeak_criterion_with_a_bogus_unit(self) -> None:
        self.assertEngineRefusal(
            "refusal_v2_leetspeak_criterion_with_a_bogus_unit", "decision-unit-unknown"
        )

    def test_refusal_v2_dimensionless_identity_is_not_a_unit(self) -> None:
        self.assertEngineRefusal(
            "refusal_v2_dimensionless_identity_is_not_a_unit", "decision-unit-unknown"
        )

    def test_refusal_v2_value_judgment_survives_an_admissible_unit(self) -> None:
        # Belt and braces: the unit is fine, the criterion is not. v2 keeps the
        # v1 word list as a second gate instead of replacing it.
        self.assertEngineRefusal(
            "refusal_v2_value_judgment_survives_an_admissible_unit",
            "decision-value-judgment",
        )

    def test_refusal_v2_alias_is_not_a_canonical_unit(self) -> None:
        self.assertEngineRefusal(
            "refusal_v2_alias_is_not_a_canonical_unit", "decision-unit-unknown"
        )

    def test_refusal_v2_unit_comparison_is_case_sensitive(self) -> None:
        self.assertEngineRefusal(
            "refusal_v2_unit_comparison_is_case_sensitive", "decision-unit-unknown"
        )

    def test_refusal_v2_duplicate_label(self) -> None:
        self.assertEngineRefusal("refusal_v2_duplicate_label", "decision-duplicate-label")

    def test_refusal_v2_top_two_tie(self) -> None:
        self.assertEngineRefusal("refusal_v2_top_two_tie", "decision-margin-zero")

    def test_refusal_v2_sense_unknown(self) -> None:
        self.assertEngineRefusal("refusal_v2_sense_unknown", "decision-sense-unknown")


class DecisionV2CheckerRefusalTest(DecisionPackCase):
    """The independent checker holds the same closed vocabulary as the engine."""

    def test_poison_v2_unit_replaced_with_a_bogus_token(self) -> None:
        self.assertCheckerRefusal(
            "poison_v2_unit_replaced_with_a_bogus_token", "cert-unit-not-admitted"
        )

    def test_poison_v2_unit_replaced_with_the_dimensionless_identity(self) -> None:
        self.assertCheckerRefusal(
            "poison_v2_unit_replaced_with_the_dimensionless_identity",
            "cert-unit-not-admitted",
        )

    def test_poison_v2_unit_key_deleted(self) -> None:
        self.assertCheckerRefusal("poison_v2_unit_key_deleted", "cert-claim-keys")

    def test_poison_v2_criterion_rewritten_to_a_value_judgment(self) -> None:
        self.assertCheckerRefusal(
            "poison_v2_criterion_rewritten_to_a_value_judgment", "cert-value-judgment"
        )

    def test_poison_v2_margin_inflated(self) -> None:
        self.assertCheckerRefusal("poison_v2_margin_inflated", "cert-margin-mismatch")

    def test_poison_v2_kind_downgraded_to_v1(self) -> None:
        self.assertCheckerRefusal("poison_v2_kind_downgraded_to_v1", "cert-kind-unexpected")

    def test_control_v2_untampered_certificate_is_still_accepted(self) -> None:
        # Non-vacuity control for the v2 tampering column: same minting call,
        # same checker, no mutation -- ACCEPT. So each refusal above is
        # attributable to its mutation rather than to the v2 lane being broken.
        row = self.row("poison_v2_unit_replaced_with_a_bogus_token")
        observed = self.engine.run("decision-rank-v2", *row["argv"])
        self.assertEqual(observed.returncode, 0, observed.stderr[-800:])
        verdict = GEN.check_decision(observed.certificate(GEN.DECISION_PREFIX))
        self.assertEqual(verdict.summary, "ACCEPT", verdict.line)

    def test_control_v1_certificates_are_unaffected_by_the_v2_lane(self) -> None:
        """The checker gained a lane; it did not change the one it had.

        A v1 certificate still verifies, and a v1 certificate with a `unit`
        smuggled into its claim is still refused on the v1 key set -- the unit
        gate does not become reachable by adding a field to a v1 envelope.
        """
        row = self.row("positive_decision_min")
        observed = self.engine.run("decision-rank", *row["argv"])
        certificate = observed.certificate(GEN.DECISION_PREFIX)
        self.assertEqual(GEN.check_decision(certificate).summary, "ACCEPT")

        payload = json.loads(certificate[len(GEN.DECISION_PREFIX) :])
        self.assertEqual(payload["schema"], "jackal-decision-cert-v1")
        payload["claim"]["unit"] = "ms"
        smuggled = GEN.DECISION_PREFIX + json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        )
        verdict = GEN.check_decision(smuggled)
        self.assertEqual(verdict.reason_class, "cert-claim-keys", verdict.line)


class DecisionV2GapClosedTest(DecisionPackCase):
    """The gap `DecisionKnownGapTest` documents, closed in the v2 lane.

    Paired assertions on the same four criteria: through v1 they still rank
    (retained unchanged for compatibility), through v2 every one is refused by a
    named class. That pairing is the evidence the closure is real -- a v2-only
    refusal list would also be produced by an operation that refuses everything.
    """

    GAP_CRITERIA = ("optimal_score", "ideal_score", "b3st", "most_elegant")

    def test_v2_refuses_every_criterion_the_v1_blocklist_misses(self) -> None:
        for criterion in self.GAP_CRITERIA:
            with self.subTest(criterion=criterion, unit="<none>"):
                # No unit slot at all: the argument list is one short.
                observed = self.engine.run(
                    "decision-rank-v2", "d_gap", criterion, "max", "alpha", "1", "beta", "2"
                )
                self.assertEqual(observed.refusal_class, "pack-request-arity")
                self.assertNotIn(GEN.DECISION_PREFIX, observed.stdout)
            with self.subTest(criterion=criterion, unit=""):
                observed = self.engine.run(
                    "decision-rank-v2", "d_gap", criterion, "", "max", "alpha", "1", "beta", "2"
                )
                self.assertEqual(observed.refusal_class, "decision-unit-missing")
                self.assertNotIn(GEN.DECISION_PREFIX, observed.stdout)
            for bogus in ("elegance", "goodness", "one", "score", "points"):
                with self.subTest(criterion=criterion, unit=bogus):
                    observed = self.engine.run(
                        "decision-rank-v2", "d_gap", criterion, bogus, "max",
                        "alpha", "1", "beta", "2",
                    )
                    self.assertEqual(
                        observed.refusal_class,
                        "decision-unit-unknown",
                        f"{criterion} in {bogus!r} was not refused by the closed vocabulary",
                    )
                    self.assertNotIn(GEN.DECISION_PREFIX, observed.stdout)

    def test_v1_still_accepts_the_same_criteria_and_is_retained_unchanged(self) -> None:
        # The compatibility half of the pair. v1 is a shipped operation with a
        # frozen corpus; v2 is additive and does not narrow v1's input surface.
        # If this ever starts failing, v1's accepted inputs changed and its
        # callers broke -- which is the outcome v2 exists to avoid.
        for criterion in self.GAP_CRITERIA:
            with self.subTest(criterion=criterion):
                observed = self.engine.run(
                    "decision-rank", "d_gap", criterion, "max", "alpha", "1", "beta", "2"
                )
                self.assertEqual(observed.returncode, 0, observed.stderr[-400:])
                certificate = observed.certificate(GEN.DECISION_PREFIX)
                self.assertIn("jackal-decision-cert-v1", certificate)
                self.assertEqual(GEN.check_decision(certificate).summary, "ACCEPT")

    def test_known_residual_v2_cannot_detect_a_mislabelled_criterion(self) -> None:
        """What v2 does NOT close, asserted rather than left as folklore.

        A caller who declares an admissible unit and names the criterion however
        they like is admitted: `most_elegant` in `ms` ranks. v2 removes the
        free-text escape (no unit exists for elegance, so the honest request is
        refused) and the word list still catches the obvious spellings, but
        nothing in this protocol can tell that a number labelled `ms` is not a
        duration. The certificate says exactly what was declared and no more.
        """
        observed = self.engine.run(
            "decision-rank-v2", "d_residual", "most_elegant", "ms", "max",
            "alpha", "1", "beta", "2",
        )
        self.assertEqual(observed.returncode, 0, observed.stderr[-400:])
        claim = self.claim(observed.certificate(GEN.DECISION_PREFIX))
        self.assertEqual(claim["unit"], "ms")
        self.assertEqual(claim["criterion"], "most_elegant")


class DecisionUnitVocabularyTest(DecisionPackCase):
    """Three copies of the unit vocabulary, forced to agree.

    The engine cannot read JSON, so its list is hardcoded in `jackal_calc.anb`;
    the checker mirrors it in `ADMITTED_UNITS`; the authority is
    `release/claim/unit_registry_v1.json`. Two vocabularies with no mechanism
    forcing agreement diverge -- this is that mechanism, and it compares against
    the registry file and a live engine rather than against a retyped copy.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.registry_units = GEN.admitted_units_from_registry()
        cls.checker = GEN._load_module("jackal_decision_verify", GEN.DECISION_CHECKER)

    def test_checker_vocabulary_is_exactly_the_registry_minus_the_exclusions(self) -> None:
        self.assertEqual(set(self.checker.ADMITTED_UNITS), set(self.registry_units))
        self.assertEqual(len(self.checker.ADMITTED_UNITS), len(set(self.checker.ADMITTED_UNITS)))
        # Non-vacuity: the exclusion list must name real registry ids, or the
        # set equality above would be comparing against a stale filter.
        document = json.loads((ROOT / GEN.UNIT_REGISTRY).read_text(encoding="utf-8"))
        for excluded in GEN.UNIT_REGISTRY_EXCLUSIONS:
            with self.subTest(excluded=excluded):
                self.assertIn(excluded, document["units"])
                self.assertNotIn(excluded, self.checker.ADMITTED_UNITS)

    def test_engine_admits_every_unit_the_registry_declares(self) -> None:
        for unit in self.registry_units:
            with self.subTest(unit=unit):
                observed = self.engine.run(
                    "decision-rank-v2", "d_units", "measured_quantity", unit, "max",
                    "alpha", "1", "beta", "2",
                )
                self.assertEqual(
                    observed.returncode,
                    0,
                    f"the registry declares {unit!r} but the engine refused it: "
                    f"{observed.refusal_class}",
                )
                claim = self.claim(observed.certificate(GEN.DECISION_PREFIX))
                self.assertEqual(claim["unit"], unit)
                self.assertEqual(
                    GEN.check_decision(observed.certificate(GEN.DECISION_PREFIX)).summary,
                    "ACCEPT",
                    f"the engine admits {unit!r} but the checker does not",
                )

    def test_engine_refuses_the_excluded_ids_and_the_registry_aliases(self) -> None:
        document = json.loads((ROOT / GEN.UNIT_REGISTRY).read_text(encoding="utf-8"))
        probes = list(GEN.UNIT_REGISTRY_EXCLUSIONS) + sorted(document["aliases"])[:6] + [
            "elegance",
            "goodness",
            "utils",
            "MS",
            "Kwh",
        ]
        for unit in probes:
            with self.subTest(unit=unit):
                observed = self.engine.run(
                    "decision-rank-v2", "d_units", "measured_quantity", unit, "max",
                    "alpha", "1", "beta", "2",
                )
                self.assertEqual(
                    observed.refusal_class,
                    "decision-unit-unknown",
                    f"{unit!r} is not an admitted canonical id but was not refused as one",
                )

    def test_instrument_removing_one_unit_turns_an_accepted_case_into_a_refusal(self) -> None:
        """Non-vacuity control on the checker's unit gate itself.

        The gate is only load-bearing if it can fail. A freshly imported copy of
        the checker verifies a real `ms` certificate, then the same certificate is
        refused after `ms` is removed from that copy's vocabulary -- with no other
        change to the certificate or to any other rule. The file on disk is never
        touched, and every subprocess-driven case in this module still runs
        against the real, unmodified checker.
        """
        row = self.row("positive_v2_declared_unit_min")
        observed = self.engine.run("decision-rank-v2", *row["argv"])
        self.assertEqual(observed.returncode, 0, observed.stderr[-800:])
        certificate = observed.certificate(GEN.DECISION_PREFIX)

        probe = GEN._load_module("probe_decision_verify_units", GEN.DECISION_CHECKER)
        self.assertIn("ms", probe.ADMITTED_UNITS)
        self.assertTrue(probe.verify(certificate))

        probe.ADMITTED_UNITS = tuple(u for u in probe.ADMITTED_UNITS if u != "ms")
        with self.assertRaises(probe.Refusal) as caught:
            probe.verify(certificate)
        self.assertEqual(caught.exception.reason_class, "cert-unit-not-admitted")

        # And the real checker, untouched on disk, still accepts it.
        self.assertEqual(GEN.check_decision(certificate).summary, "ACCEPT")


class DecisionCheckerGuardsAreLoadBearingTest(DecisionPackCase):
    """Attribute each checker refusal to the guard that causes it.

    The corpus rows show that a tampered certificate is refused. They do not by
    themselves show *which* recomputation catches it. These probes call the
    checker in-process on a private import so one guard at a time can be removed;
    the file on disk is never touched, and every subprocess-driven case above
    still runs against the real, unmodified checker.
    """

    def _probe_checker(self):
        return GEN._load_module("probe_decision_verify", GEN.DECISION_CHECKER)

    def _minted(self, *argv: str) -> str:
        observed = self.engine.run("decision-rank", *argv)
        self.assertEqual(observed.returncode, 0, observed.stderr[-800:])
        return observed.certificate(GEN.DECISION_PREFIX)

    def test_instrument_margin_recomputation_is_what_refuses_an_inflated_margin(self) -> None:
        row = self.row("poison_margin_inflated")
        certificate = self._minted(*row["argv"])
        tampered = GEN.apply_tamper(certificate, GEN.DECISION_PREFIX, row["tamper"])

        probe = self._probe_checker()
        # Control: the shipped recomputation refuses the tampered certificate and
        # accepts the untouched one, so only the margin field is in play.
        with self.assertRaises(probe.Refusal) as caught:
            probe.verify(tampered)
        self.assertEqual(caught.exception.reason_class, "cert-margin-mismatch")
        notes = probe.verify(certificate)
        # The true gap is taken from the unmodified checker's own note, before any
        # patching, so the substituted value below is not invented here.
        matched = re.search(r"margin recomputed (-?\d+)", "\n".join(notes))
        self.assertIsNotNone(matched)
        assert matched is not None
        true_margin = int(matched.group(1))
        self.assertNotEqual(str(true_margin), row["tamper"]["value"])

        # Stand in for a checker that trusts the certificate's own margin: make
        # the claimed margin parse as that true gap, leaving every other field and
        # every other rule exactly as shipped. The identical tampered certificate
        # is then admitted, so the margin comparison -- and nothing else -- is what
        # refused it above.
        original_int = probe._require_integer

        def believe_claimed_margin(value, field):
            if field == "margin":
                return true_margin
            return original_int(value, field)

        probe._require_integer = believe_claimed_margin
        self.assertTrue(probe.verify(tampered))

    def test_instrument_value_judgment_blocklist_is_what_refuses_a_renamed_criterion(self) -> None:
        row = self.row("poison_criterion_rewritten_to_a_value_judgment")
        certificate = self._minted(*row["argv"])
        tampered = GEN.apply_tamper(certificate, GEN.DECISION_PREFIX, row["tamper"])

        probe = self._probe_checker()
        with self.assertRaises(probe.Refusal) as caught:
            probe.verify(tampered)
        self.assertEqual(caught.exception.reason_class, "cert-value-judgment")

        # Empty the blocklist and the same certificate is admitted -- which is
        # also the reason the blocklist gap in DecisionKnownGapTest matters: this
        # guard is the only thing standing between a value judgment and a
        # certificate.
        probe.VALUE_JUDGMENT_WORDS = ()
        self.assertTrue(probe.verify(tampered))

    def test_instrument_probe_import_is_isolated_from_the_real_checker(self) -> None:
        """The probes above must not contaminate the subprocess checker.

        Each `_load_module` call executes a fresh module object, and the real
        checker runs as a separate process anyway. Both halves are asserted here
        so a future refactor that starts caching the import is caught.
        """
        first = self._probe_checker()
        first.VALUE_JUDGMENT_WORDS = ()
        second = self._probe_checker()
        self.assertNotEqual(second.VALUE_JUDGMENT_WORDS, ())
        row = self.row("poison_criterion_rewritten_to_a_value_judgment")
        certificate = self._minted(*row["argv"])
        tampered = GEN.apply_tamper(certificate, GEN.DECISION_PREFIX, row["tamper"])
        verdict = GEN.check_decision(tampered)
        self.assertEqual(verdict.reason_class, "cert-value-judgment", verdict.line)


class DecisionCorpusReplayTest(DecisionPackCase):
    def test_every_frozen_case_replays_identically(self) -> None:
        for case_id in sorted(self.rows):
            with self.subTest(case=case_id):
                self.replay(case_id)

    def test_every_frozen_case_is_named_by_an_individual_test(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        unnamed = [case_id for case_id in sorted(self.rows) if f'"{case_id}"' not in source]
        self.assertEqual(unnamed, [])


class DecisionCaseCensusTest(DecisionPackCase):
    def test_case_census(self) -> None:
        positive = [n for n in dir(DecisionPositiveTest) if n.startswith("test_positive_")]
        refusal = [n for n in dir(DecisionEngineRefusalTest) if n.startswith("test_refusal_")]
        poison = [n for n in dir(DecisionCheckerRefusalTest) if n.startswith("test_poison_")]
        control = [
            n
            for n in dir(DecisionCheckerRefusalTest) + dir(DecisionKnownGapTest)
            if n.startswith("test_control_") or "does_catch" in n
        ]
        gaps = [n for n in dir(DecisionKnownGapTest) if n.startswith("test_known_gap_")]
        instrument = [
            n
            for n in dir(DecisionCheckerGuardsAreLoadBearingTest) + dir(DecisionHarnessTest)
            if n.startswith("test_instrument_") or n.startswith("test_")
        ]
        # The v2 lane is counted separately so a census that stays flat while v2
        # grows is visible rather than absorbed into the v1 totals.
        v2_positive = [n for n in dir(DecisionV2PositiveTest) if n.startswith("test_positive_v2_")]
        v2_refusal = [n for n in dir(DecisionV2EngineRefusalTest) if n.startswith("test_refusal_v2_")]
        v2_poison = [n for n in dir(DecisionV2CheckerRefusalTest) if n.startswith("test_poison_v2_")]
        v2_control = [
            n
            for n in dir(DecisionV2CheckerRefusalTest) + dir(DecisionV2GapClosedTest)
            if n.startswith("test_control_") or n.startswith("test_known_residual_")
        ]
        v2_vocabulary = [n for n in dir(DecisionUnitVocabularyTest) if n.startswith("test_")]
        print(
            f"\ndecision_case_census positive={len(positive)} "
            f"engine_refusal={len(refusal)} checker_refusal={len(poison)} "
            f"control={len(control)} known_gap={len(gaps)} "
            f"instrument={len(instrument)} "
            f"v2_positive={len(v2_positive)} v2_engine_refusal={len(v2_refusal)} "
            f"v2_checker_refusal={len(v2_poison)} v2_control={len(v2_control)} "
            f"v2_vocabulary={len(v2_vocabulary)} "
            f"corpus_cases={len(self.rows)} corpus_counts={self.corpus['case_counts']}",
            file=sys.stderr,
        )
        self.assertGreaterEqual(len(positive), 5)
        self.assertGreaterEqual(len(refusal), 7)
        self.assertGreaterEqual(len(poison), 8)
        self.assertGreaterEqual(len(control), 2)
        self.assertGreaterEqual(len(gaps), 1)
        self.assertGreaterEqual(len(instrument), 8)
        self.assertGreaterEqual(len(v2_positive), 4)
        self.assertGreaterEqual(len(v2_refusal), 9)
        self.assertGreaterEqual(len(v2_poison), 6)
        self.assertGreaterEqual(len(v2_control), 3)
        self.assertGreaterEqual(len(v2_vocabulary), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
