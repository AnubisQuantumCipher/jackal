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
    """Gaps that are open today, asserted as gaps.

    A test that pins current behaviour is not an endorsement of it. These exist
    so that the next person reads the limitation from a test rather than
    rediscovering it in production.
    """

    def test_known_gap_substring_blocklist_misses_optimal(self) -> None:
        """`optimal` and `b3st` pass a substring blocklist. They should not.

        `require_measurable_criterion` refuses a criterion whose lowercased text
        contains any of a fixed word list (`better`, `best`, `worth`, ...). That
        catches the obvious spellings and nothing else. A criterion named
        `optimal_score` is exactly as much a value judgment as `best_score`, and
        `b3st` is the same word with a digit in it, yet both are ACCEPTED
        end-to-end by the engine AND by the independent checker.

        This test asserts the ACCEPT deliberately. It documents the gap; it does
        not bless it.

        Closing it needs a different mechanism, not a longer word list: a
        blocklist over free text can always be spelled around. The fix is to
        require a *declared unit* on the criterion (`ms`, `rps`, `bytes`,
        `ppm`, ...) drawn from a closed vocabulary, so that admissibility is
        decided by what the number measures rather than by which letters the
        caller chose. Until that lands, this pack can be handed a value judgment
        with a creative name and will rank on it.
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
        print(
            f"\ndecision_case_census positive={len(positive)} "
            f"engine_refusal={len(refusal)} checker_refusal={len(poison)} "
            f"control={len(control)} known_gap={len(gaps)} "
            f"instrument={len(instrument)} "
            f"corpus_cases={len(self.rows)} corpus_counts={self.corpus['case_counts']}",
            file=sys.stderr,
        )
        self.assertGreaterEqual(len(positive), 5)
        self.assertGreaterEqual(len(refusal), 7)
        self.assertGreaterEqual(len(poison), 8)
        self.assertGreaterEqual(len(control), 2)
        self.assertGreaterEqual(len(gaps), 1)
        self.assertGreaterEqual(len(instrument), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
