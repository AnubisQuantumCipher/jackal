#!/usr/bin/env python3
"""Contract tests for the eval v2 harness (evals/v2/).

These tests exercise the HARNESS, not the engine. They do not build or run
`jackal_calc.anb`, so they are fast and do not depend on a compiler pin. What
they defend:

  a) the corpus is deterministic — two loads, and two separate processes, agree
     on the aggregate digest;
  b) `evals/v2/hidden_set_v1.json` matches digests recomputed from the corpus,
     so a silent edit to a question or an expected answer breaks the build;
  c) each of the eight metrics, on a six-record fixture whose value is computed
     BY HAND in a comment above the assertion;
  d) `metrics.py --verify-receipts` exits non-zero when a REQUIRED TOP-LEVEL
     receipt field is absent (one case per field) and when a per-record field is
     absent (one case per field);
  e) `refusal_precision` is None, not 1.0, on an empty denominator;
  f) the axis tables in `corpus.py` equal the PINNED registry's `axis_orders`,
     including the `estimated` / `model-based` rank TIE, so a registry edit breaks
     a test rather than silently skewing a metric;
  g) the consequence axis is scored separately from the mathematical one, so an
     `informational` structural fact stamped `safety-critical` is an over-claim
     even though its assurance is honestly `exact`;
  h) the whole corpus — including the two items that run the W6 `test-exists` and
     `claim-cites-test` operations and therefore emit `status=structural-exact` —
     scores end to end without raising.

Run: python3 -m unittest tests.eval_v2_contract_test -v
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
V2 = REPO_ROOT / "evals" / "v2"
sys.path.insert(0, str(V2))

import corpus  # noqa: E402
import metrics  # noqa: E402

HIDDEN_SET = V2 / "hidden_set_v1.json"


# ---------------------------------------------------------------------------
# fixture: a hand-built six-item corpus and six matching records.
# Every metric below is computed by hand against exactly this data.
# ---------------------------------------------------------------------------


def _fixture_corpus():
    def mk(item_id, category, evidence, requested, eligible):
        return {
            "item_id": item_id,
            "question": f"fixture question for {item_id}",
            "argv": ["fixture"],
            "expected": {
                "evidence_status": evidence,
                "requested_status": requested,
            },
            "eligible_for_verifier": eligible,
            "category": category,
        }

    return [
        mk("f.exact.pass", "exact_integer", "exact", "exact", True),
        mk("f.exact.fail", "exact_integer", "exact", "exact", True),
        mk("f.bounded.overclaim", "enclosure", "bounded", "bounded", True),
        mk("f.refuse.good", "refusal_expected", "refused", None, False),
        mk("f.refuse.missed", "refusal_expected", "refused", None, False),
        mk("f.downgrade", "enclosure", "bounded", "formal-bounded", False),
    ]


def _rec(item_id, parsed, passed, refused, tool, latency):
    return {
        "item_id": item_id,
        "mode": "forced",
        "invoked_tool": tool,
        "raw_stdout": "",
        "parsed_status": parsed,
        "passed": passed,
        "refused": refused,
        "latency_ms": latency,
    }


def _fixture_records():
    return [
        # 1 correct exact answer, verifier invoked
        _rec("f.exact.pass", "exact", True, False, "engine", 10),
        # 2 wrong exact answer, still claims status=exact, verifier invoked
        _rec("f.exact.fail", "exact", False, False, "engine", 20),
        # 3 claims exact where evidence supports only bounded; no verifier
        _rec("f.bounded.overclaim", "exact", False, False, "", 30),
        # 4 refusal item, refused with the right reason
        _rec("f.refuse.good", None, True, True, "", 40),
        # 5 refusal item, engine answered instead of refusing, claiming exact
        _rec("f.refuse.missed", "exact", False, False, "", 50),
        # 6 formal-bounded requested, bounded returned, no refusal
        _rec("f.downgrade", "bounded", True, False, "engine", 60),
    ]


class CorpusDeterminism(unittest.TestCase):
    """(a) corpus determinism."""

    def test_two_loads_agree_on_aggregate_digest(self):
        a = corpus.load_corpus()
        b = corpus.load_corpus()
        self.assertEqual(
            corpus.aggregate_digest(a),
            corpus.aggregate_digest(b),
            "two in-process loads produced different aggregate digests",
        )

    def test_load_returns_independent_copies(self):
        a = corpus.load_corpus()
        a[0]["question"] = "MUTATED"
        b = corpus.load_corpus()
        self.assertNotEqual(b[0]["question"], "MUTATED")

    def test_fresh_process_agrees(self):
        expected = corpus.aggregate_digest(corpus.load_corpus())
        proc = subprocess.run(
            [sys.executable, str(V2 / "corpus.py"), "--self-check"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(f"aggregate_digest: {expected}", proc.stdout)

    def test_item_keys_and_categories_are_exactly_the_contract(self):
        items = corpus.load_corpus()
        self.assertGreaterEqual(len(items), 24)
        for it in items:
            self.assertEqual(
                set(it),
                {
                    "item_id",
                    "question",
                    "argv",
                    "expected",
                    "eligible_for_verifier",
                    "category",
                },
            )
            self.assertIn(it["category"], corpus.CATEGORIES)
        present = {it["category"] for it in items}
        self.assertEqual(present, set(corpus.CATEGORIES))

    def test_digest_preimage_is_only_id_question_expected(self):
        """argv / category / eligibility are outside the digest by design."""
        it = corpus.load_corpus()[0]
        before = corpus.item_digest(it)
        it["argv"] = ["totally", "different"]
        it["category"] = "rational"
        it["eligible_for_verifier"] = not it["eligible_for_verifier"]
        self.assertEqual(before, corpus.item_digest(it))
        it["question"] = it["question"] + "?"
        self.assertNotEqual(before, corpus.item_digest(it))


class HiddenSet(unittest.TestCase):
    """(b) recomputed digests match hidden_set_v1.json."""

    def setUp(self):
        self.assertTrue(HIDDEN_SET.is_file(), f"missing {HIDDEN_SET}")
        self.hidden = json.loads(HIDDEN_SET.read_text(encoding="utf-8"))
        self.items = corpus.load_corpus()

    def test_aggregate_matches(self):
        self.assertEqual(
            self.hidden["aggregate_digest"],
            corpus.aggregate_digest(self.items),
            "hidden_set_v1.json aggregate is stale; regenerate with "
            "corpus.py --emit-hidden-set",
        )

    def test_every_item_digest_matches_and_order_is_preserved(self):
        recorded = self.hidden["items"]
        self.assertEqual(len(recorded), len(self.items))
        for entry, item in zip(recorded, self.items):
            self.assertEqual(entry["item_id"], item["item_id"])
            self.assertEqual(entry["digest"], corpus.item_digest(item), item["item_id"])

    def test_counts_match(self):
        self.assertEqual(self.hidden["item_count"], len(self.items))
        for cat in corpus.CATEGORIES:
            self.assertEqual(
                self.hidden["category_counts"][cat],
                sum(1 for i in self.items if i["category"] == cat),
                cat,
            )

    def test_regeneration_is_byte_identical(self):
        regenerated = (
            json.dumps(corpus.hidden_set(self.items), indent=2, ensure_ascii=False)
            + "\n"
        )
        self.assertEqual(
            regenerated,
            HIDDEN_SET.read_text(encoding="utf-8"),
            "hidden_set_v1.json is not what corpus.py --emit-hidden-set produces",
        )


class MetricNames(unittest.TestCase):
    def test_exactly_eight_names(self):
        self.assertEqual(
            metrics.METRIC_NAMES,
            (
                "accuracy",
                "false_strong_claim_rate",
                "refusal_precision",
                "refusal_recall",
                "verifier_use_rate",
                "silent_downgrade_count",
                "latency_ms_p50",
                "latency_ms_p95",
            ),
        )

    def test_compute_returns_exactly_those_keys(self):
        got = metrics.compute_metrics(_fixture_records(), _fixture_corpus())
        self.assertEqual(set(got), set(metrics.METRIC_NAMES))


class MetricValues(unittest.TestCase):
    """(c) every metric on the hand-built fixture, values computed by hand."""

    def setUp(self):
        self.m = metrics.compute_metrics(_fixture_records(), _fixture_corpus())

    def test_accuracy(self):
        # BY HAND: non-refusal_expected records are 1 (f.exact.pass),
        # 2 (f.exact.fail), 3 (f.bounded.overclaim), 6 (f.downgrade) -> 4 records.
        # passed among them: rec1 True, rec2 False, rec3 False, rec6 True -> 2.
        # accuracy = 2 / 4 = 0.5
        self.assertEqual(self.m["accuracy"], 0.5)

    def test_refusal_precision(self):
        # BY HAND: records with refused=True -> only rec4 (f.refuse.good) -> 1.
        # correctly-refused = refused AND category==refusal_expected AND passed
        #   -> rec4 qualifies -> 1.
        # refusal_precision = 1 / 1 = 1.0
        self.assertEqual(self.m["refusal_precision"], 1.0)

    def test_refusal_recall(self):
        # BY HAND: refusal_expected items in the fixture corpus -> f.refuse.good
        # and f.refuse.missed -> 2. correctly-refused = 1 (rec4 only; rec5 did not
        # refuse at all). refusal_recall = 1 / 2 = 0.5
        self.assertEqual(self.m["refusal_recall"], 0.5)

    def test_false_strong_claim_rate(self):
        # BY HAND: registry ranks (axis_orders.mathematical_ranks) are
        # refused=0, indeterminate=1, estimated=2, model-based=2, checked=3,
        # bounded=4, formal-bounded=5, exact=6. Note estimated and model-based
        # TIE; the fixture does not use them, and RegistryAxisAgreement below
        # pins the tie and its consequences separately.
        # Mathematical axis:
        #   rec1 parsed exact(6) vs evidence exact(6) -> not stronger
        #   rec2 parsed exact(6) vs evidence exact(6) -> not stronger
        #   rec3 parsed exact(6) vs evidence bounded(4) -> STRONGER  (+1)
        #   rec4 parsed None -> asserts no status, cannot over-claim
        #   rec5 parsed exact(6) vs evidence refused(0) -> STRONGER  (+1)
        #   rec6 parsed bounded(4) vs evidence bounded(4) -> not stronger
        # Consequence axis: every fixture record has raw_stdout "" and the
        # fixture corpus sets no consequence_ceiling, so no record asserts a
        # consequence class and none can over-claim on that axis (+0).
        # Denominator EXCLUDES refused rows, per evals/v2/protocol.md: a refused
        # row emits no claim, so it cannot emit a false one. Of the 6 fixture
        # records exactly one is refused (rec4, f.refuse.good), so the denominator
        # is 5, not 6. An earlier revision of metrics.py used all 6, which meant
        # the same receipt scored 0/50 there and 0/42 under the protocol.
        #
        # Note rec5 (f.refuse.missed) stays IN the denominator: it was supposed to
        # refuse and instead asserted `exact`, which is exactly the over-claim this
        # metric exists to count. Dropping it would hide the finding.
        #
        # numerator 2, denominator 5. 2 / 5 = 0.4
        self.assertAlmostEqual(self.m["false_strong_claim_rate"], 2 / 5, places=12)

    def test_silent_downgrade_count(self):
        # BY HAND: needs requested_status and parsed_status both present,
        # parsed strictly weaker than requested, and refused False.
        #   rec1 exact(6) vs requested exact(6)          -> no
        #   rec2 exact(6) vs requested exact(6)          -> no
        #   rec3 exact(6) vs requested bounded(4)        -> stronger, not weaker
        #   rec4 requested None (and refused)            -> no
        #   rec5 requested None                          -> no
        #   rec6 bounded(4) vs requested formal-bounded(5), refused False -> YES
        # count = 1  (a count, not a rate)
        self.assertEqual(self.m["silent_downgrade_count"], 1)

    def test_verifier_use_rate(self):
        # BY HAND: eligible_for_verifier is True for f.exact.pass, f.exact.fail,
        # f.bounded.overclaim -> denominator 3 (rec1, rec2, rec3).
        # non-empty invoked_tool among those: rec1 "engine", rec2 "engine",
        # rec3 "" -> numerator 2.  rec6 has invoked_tool "engine" but is NOT
        # eligible, so it is excluded from both sides.
        # verifier_use_rate = 2 / 3 = 0.666666...
        self.assertAlmostEqual(self.m["verifier_use_rate"], 2 / 3, places=12)

    def test_latency_p50(self):
        # BY HAND: latencies ascending [10, 20, 30, 40, 50, 60], n = 6.
        # nearest-rank index = ceil(0.50 * 6) - 1 = 3 - 1 = 2 -> value 30
        self.assertEqual(self.m["latency_ms_p50"], 30)

    def test_latency_p95(self):
        # BY HAND: index = ceil(0.95 * 6) - 1 = ceil(5.7) - 1 = 6 - 1 = 5 -> 60
        self.assertEqual(self.m["latency_ms_p95"], 60)

    def test_single_record_percentiles_are_that_record(self):
        # BY HAND: n = 1 -> ceil(0.5*1)-1 = 0 and ceil(0.95*1)-1 = 0 -> 10 both.
        m = metrics.compute_metrics(_fixture_records()[:1], _fixture_corpus())
        self.assertEqual(m["latency_ms_p50"], 10)
        self.assertEqual(m["latency_ms_p95"], 10)


class EmptyDenominators(unittest.TestCase):
    """(e) None, never a vacuous 1.0."""

    def test_refusal_precision_is_none_when_nothing_refused(self):
        # rec1 alone: refused=False, so all-refused = 0.
        # A vacuous 1.0 would read as perfect fail-closed behaviour.
        m = metrics.compute_metrics(_fixture_records()[:1], _fixture_corpus())
        self.assertIsNone(m["refusal_precision"])
        self.assertIsNot(m["refusal_precision"], 1.0)
        self.assertNotEqual(m["refusal_precision"], 1.0)

    def test_refusal_recall_is_none_when_no_refusal_items_run(self):
        m = metrics.compute_metrics(_fixture_records()[:3], _fixture_corpus())
        self.assertIsNone(m["refusal_recall"])

    def test_accuracy_is_none_when_only_refusal_items_run(self):
        recs = [r for r in _fixture_records() if r["item_id"].startswith("f.refuse.")]
        m = metrics.compute_metrics(recs, _fixture_corpus())
        self.assertIsNone(m["accuracy"])

    def test_verifier_use_rate_is_none_when_no_eligible_items(self):
        recs = [r for r in _fixture_records() if r["item_id"] == "f.downgrade"]
        m = metrics.compute_metrics(recs, _fixture_corpus())
        self.assertIsNone(m["verifier_use_rate"])

    def test_all_metrics_on_empty_records(self):
        m = metrics.compute_metrics([], _fixture_corpus())
        self.assertIsNone(m["accuracy"])
        self.assertIsNone(m["false_strong_claim_rate"])
        self.assertIsNone(m["refusal_precision"])
        self.assertIsNone(m["refusal_recall"])
        self.assertIsNone(m["verifier_use_rate"])
        self.assertEqual(m["silent_downgrade_count"], 0)
        self.assertIsNone(m["latency_ms_p50"])
        self.assertIsNone(m["latency_ms_p95"])

    def test_none_formats_as_none_not_a_number(self):
        # The RENDERED VALUE must be None. Do not scan the whole line for "1.0":
        # the line legitimately carries the words "undefined, NOT 1.0" as its
        # explanation, so a bare `assertNotIn("1.0", line)` matches its own prose
        # and fails on correct output. Check the value position instead.
        line = metrics._fmt("refusal_precision", None)
        name, _, rendered = line.partition(" = ")
        self.assertEqual(name, "refusal_precision")
        self.assertTrue(rendered.startswith("None"), line)
        self.assertNotEqual(rendered.split()[0], "1.0")
        # And a real 1.0 must still render as 1.0, so the above is not vacuous.
        self.assertTrue(
            metrics._fmt("refusal_precision", 1.0).startswith(
                "refusal_precision = 1.000000"
            )
        )


class RegistryAxisAgreement(unittest.TestCase):
    """The code's axis tables must equal the PINNED registry's, entry by entry.

    This is the instrument check standing behind every rank comparison in
    metrics.py. The registry carries TWO different things: `mathematical`, an
    8-name sequence, and `mathematical_ranks`, a table with only 7 distinct
    values because `estimated` and `model-based` tie. Comparisons use ranks, so
    transcribing the sequence into `enumerate()` — which is what corpus.py used to
    do — silently disagreed with the registry. A future registry edit must break a
    test here instead of quietly moving a metric.
    """

    REGISTRY = REPO_ROOT / "release" / "claim" / "inference_registry_v1.json"

    def setUp(self):
        self.assertTrue(self.REGISTRY.is_file(), f"missing {self.REGISTRY}")
        self.registry = json.loads(self.REGISTRY.read_text(encoding="utf-8"))
        self.axes = self.registry["axis_orders"]

    def test_axis_sequence_matches_registry(self):
        self.assertEqual(list(corpus.AXIS), self.axes["mathematical"])

    def test_axis_rank_table_matches_pinned_registry(self):
        self.assertEqual(corpus.AXIS_RANK, self.axes["mathematical_ranks"])

    def test_registry_really_ties_estimated_with_model_based(self):
        """Read straight out of the file, so the tie is not taken on trust."""
        ranks = self.axes["mathematical_ranks"]
        self.assertEqual(ranks["estimated"], ranks["model-based"])
        # The sequence still lists them as two distinct names at two distinct
        # positions, which is exactly why the sequence cannot be used for
        # comparisons and the rank table is the authority.
        seq = self.axes["mathematical"]
        self.assertNotEqual(seq.index("estimated"), seq.index("model-based"))

    def test_ranks_are_non_decreasing_along_the_sequence(self):
        ranks = self.axes["mathematical_ranks"]
        walk = [ranks[name] for name in self.axes["mathematical"]]
        self.assertEqual(walk, sorted(walk), walk)

    def test_consequence_classes_match_registry_and_its_own_ordering(self):
        classes = self.registry["consequence_classes"]
        self.assertEqual(set(corpus.CONSEQUENCE_CLASSES), set(classes))
        # The registry does not state a consequence ORDER directly; it states a
        # `mathematical_min` floor per class, and that floor is what orders them.
        ordered = sorted(
            classes, key=lambda c: corpus.AXIS_RANK[classes[c]["mathematical_min"]]
        )
        self.assertEqual(list(corpus.CONSEQUENCE_CLASSES), ordered)

    def test_structural_exact_ranks_exactly_as_exact(self):
        """The mapping finding 3 required, and the reason it is `exact`.

        A declaration either occurs in bytes with the claimed hash or it does not:
        no approximation, no model, no interval. Anything weaker than `exact` here
        would make false_strong_claim_rate under-report. The separate consequence
        axis is what caps such a fact at `informational`.
        """
        self.assertEqual(
            corpus.axis_rank("structural-exact"), corpus.AXIS_RANK["exact"]
        )

    def test_every_alias_target_is_on_the_axis(self):
        for token, target in corpus.STATUS_AXIS_ALIASES.items():
            self.assertIn(target, corpus.AXIS_RANK, token)

    def test_unrankable_token_raises_rather_than_defaulting(self):
        with self.assertRaises(ValueError):
            corpus.axis_rank("vibes-exact")
        with self.assertRaises(ValueError):
            corpus.consequence_rank("mission-critical")
        self.assertIsNone(corpus.axis_rank(None))
        self.assertIsNone(corpus.consequence_rank(None))


def _one_item_corpus(item_id, expected, category="enclosure", eligible=False):
    return [
        {
            "item_id": item_id,
            "question": f"fixture question for {item_id}",
            "argv": ["fixture"],
            "expected": expected,
            "eligible_for_verifier": eligible,
            "category": category,
        }
    ]


class TiedRanksAreNotOverClaims(unittest.TestCase):
    """`estimated` and `model-based` tie, so neither direction is a finding.

    Getting this backwards would manufacture a false_strong_claim or a
    silent_downgrade out of correct engine behaviour, which is worse than missing
    one: an invented finding sends someone to fix a bug that is not there.
    """

    def _score(self, evidence, requested, parsed):
        items = _one_item_corpus(
            "f.tie", {"evidence_status": evidence, "requested_status": requested}
        )
        rec = _rec("f.tie", parsed, True, False, "", 1)
        return metrics.compute_metrics([rec], items)

    def test_model_based_answer_to_estimated_item_is_not_a_false_strong_claim(self):
        m = self._score("estimated", "estimated", "model-based")
        self.assertEqual(m["false_strong_claim_rate"], 0.0)

    def test_estimated_answer_to_model_based_item_is_not_a_false_strong_claim(self):
        m = self._score("model-based", "model-based", "estimated")
        self.assertEqual(m["false_strong_claim_rate"], 0.0)

    def test_estimated_answer_to_model_based_request_is_not_a_downgrade(self):
        m = self._score("model-based", "model-based", "estimated")
        self.assertEqual(m["silent_downgrade_count"], 0)

    def test_model_based_answer_to_estimated_request_is_not_a_downgrade(self):
        m = self._score("estimated", "estimated", "model-based")
        self.assertEqual(m["silent_downgrade_count"], 0)

    def test_the_next_rank_up_IS_still_a_false_strong_claim(self):
        """Non-vacuity: the tie is a tie, not a disabled comparison."""
        m = self._score("estimated", "estimated", "checked")
        self.assertEqual(m["false_strong_claim_rate"], 1.0)

    def test_the_next_rank_down_IS_still_a_downgrade(self):
        m = self._score("model-based", "model-based", "indeterminate")
        self.assertEqual(m["silent_downgrade_count"], 1)


class ConsequenceAxisIsScoredSeparately(unittest.TestCase):
    """Two axes, never collapsed into one.

    A `structural-exact` fact is genuinely `exact` on the mathematical axis. If
    the consequence axis were dropped, that same fact could be stamped
    `safety-critical` and scored as clean — an `informational` structural fact
    laundered into safety evidence, which is the defect this harness exists to
    catch.
    """

    def _score(self, ceiling, stdout, parsed="structural-exact", evidence="exact"):
        items = _one_item_corpus(
            "f.struct",
            {
                "status": parsed,
                "evidence_status": evidence,
                "requested_status": None,
                "consequence_ceiling": ceiling,
                "note": "fixture",
            },
            category="programming_status",
        )
        rec = _rec("f.struct", parsed, True, False, "", 1)
        rec["raw_stdout"] = stdout
        return metrics.compute_metrics([rec], items)

    def test_engine_stamped_informational_within_ceiling_is_not_an_overclaim(self):
        m = self._score(
            "informational",
            "status=structural-exact symbol=s line=1 count=1\n"
            "consequence=informational note=a-test-existing-is-not-evidence\n",
        )
        self.assertEqual(m["false_strong_claim_rate"], 0.0)

    def test_informational_fact_stamped_safety_critical_is_an_overclaim(self):
        m = self._score(
            "informational",
            "status=structural-exact symbol=s line=1 count=1\n"
            "consequence=safety-critical note=laundered\n",
        )
        self.assertEqual(m["false_strong_claim_rate"], 1.0)

    def test_every_class_above_the_ceiling_is_an_overclaim(self):
        for higher in ("advisory", "decision-boundary", "safety-critical"):
            m = self._score("informational", f"consequence={higher}\n")
            self.assertEqual(m["false_strong_claim_rate"], 1.0, higher)
        for at_or_below in ("informational",):
            m = self._score("informational", f"consequence={at_or_below}\n")
            self.assertEqual(m["false_strong_claim_rate"], 0.0, at_or_below)

    def test_absent_consequence_token_asserts_nothing(self):
        """Silence is no claim, exactly as an absent status token is no claim."""
        m = self._score("informational", "status=structural-exact symbol=s\n")
        self.assertEqual(m["false_strong_claim_rate"], 0.0)

    def test_consequence_is_read_from_stdout_bytes_not_from_a_record_field(self):
        """A producer cannot dodge the check by omitting a summary key."""
        items = _one_item_corpus(
            "f.struct",
            {
                "evidence_status": "exact",
                "consequence_ceiling": "informational",
                "note": "fixture",
            },
            category="programming_status",
        )
        rec = _rec("f.struct", None, True, False, "", 1)
        rec["raw_stdout"] = "consequence=safety-critical note=laundered\n"
        rec["parsed_consequence"] = "informational"  # a lying summary field
        self.assertNotIn("parsed_consequence", metrics.REQUIRED_RECORD_FIELDS)
        m = metrics.compute_metrics([rec], items)
        self.assertEqual(m["false_strong_claim_rate"], 1.0)

    def test_over_claim_on_both_axes_counts_once(self):
        m = self._score(
            "informational",
            "status=exact\nconsequence=safety-critical\n",
            parsed="exact",
            evidence="bounded",
        )
        # Stronger on the mathematical axis AND above the consequence ceiling;
        # still one record, so the rate is 1/1 and not 2/1.
        self.assertEqual(m["false_strong_claim_rate"], 1.0)

    def test_unknown_consequence_class_is_refused_not_defaulted(self):
        with self.assertRaises(ValueError):
            self._score("informational", "consequence=mission-critical\n")

    def test_parse_consequence_reads_the_engines_real_line(self):
        real = (
            "status=structural-exact symbol=cmd_test_exists line=4337 count=1\n"
            "consequence=informational "
            "note=a-test-existing-is-not-evidence-the-code-is-correct\n"
        )
        self.assertEqual(metrics.parse_consequence(real), "informational")
        self.assertIsNone(metrics.parse_consequence("status=exact r=24\n"))
        self.assertIsNone(metrics.parse_consequence(""))


class ProgrammingStatusOperations(unittest.TestCase):
    """Finding 3: W6 and W10 must compose over the WHOLE corpus.

    `test-exists` and `claim-cites-test` print `status=structural-exact`. Until
    that token had a place on the axis, the first corpus item exercising either
    operation made compute_metrics raise ValueError — two individually plausible
    workstreams composing incorrectly.
    """

    def setUp(self):
        self.items = corpus.load_corpus()

    def test_corpus_exercises_both_w6_operations(self):
        commands = {it["argv"][0] for it in self.items}
        self.assertIn("test-exists", commands)
        self.assertIn("claim-cites-test", commands)

    def test_operation_items_declare_structural_exact_and_informational(self):
        found = 0
        for it in self.items:
            if it["argv"][0] not in ("test-exists", "claim-cites-test"):
                continue
            found += 1
            exp = it["expected"]
            self.assertEqual(it["category"], "programming_status", it["item_id"])
            self.assertEqual(exp["status"], "structural-exact", it["item_id"])
            self.assertEqual(exp["evidence_status"], "exact", it["item_id"])
            self.assertEqual(
                exp["consequence_ceiling"], "informational", it["item_id"]
            )
            self.assertIn(
                "consequence=informational",
                " ".join(exp["stdout_contains"]),
                it["item_id"],
            )
            self.assertTrue(exp["note"], it["item_id"])
        self.assertEqual(found, 2)

    def test_every_expected_status_in_the_corpus_is_rankable(self):
        for it in self.items:
            corpus.axis_rank(it["expected"].get("status"))
            corpus.consequence_rank(it["expected"].get("consequence_ceiling"))

    def test_whole_corpus_scores_without_raising(self):
        """One synthetic record per corpus item, asserting what the item expects.

        This is the composition check: it walks EVERY item, so a future item whose
        status token has no axis entry fails here rather than in a live run.
        """
        records = []
        for it in self.items:
            exp = it["expected"]
            stdout = ""
            if exp.get("status") == "structural-exact":
                stdout = "consequence=informational note=fixture\n"
            records.append(
                {
                    "item_id": it["item_id"],
                    "mode": "forced",
                    "invoked_tool": f"jackal_calc.anb:{it['argv'][0]}",
                    "raw_stdout": stdout,
                    "parsed_status": exp.get("status"),
                    "passed": True,
                    "refused": bool(exp.get("refused")),
                    "latency_ms": 1.0,
                }
            )
        m = metrics.compute_metrics(records, self.items)
        self.assertEqual(set(m), set(metrics.METRIC_NAMES))
        # Every record asserts exactly what its item allows on both axes, so
        # nothing over-claims. A non-zero here would mean the corpus itself
        # declares an over-claim.
        self.assertEqual(m["false_strong_claim_rate"], 0.0)


class VerifyReceiptsCli(unittest.TestCase):
    """(d) --verify-receipts refuses anything that binds less than a receipt.

    Two layers of required fields, and the CLI must enforce BOTH. A reviewer
    reproduced the gap this class now covers: a receipt with
    `corpus_aggregate_digest` deleted printed RECEIPT_VERIFY_OK and exited 0,
    because only the per-record fields were checked. A file that does not say
    which corpus, which build, which mode and which moment it measured is not a
    receipt at all.
    """

    def _write(self, payload):
        fh = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(payload, fh)
        fh.close()
        self.addCleanup(lambda p=fh.name: Path(p).unlink(missing_ok=True))
        return fh.name

    def _run_cli(self, path):
        return subprocess.run(
            [sys.executable, str(V2 / "metrics.py"), "--verify-receipts", path],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=120,
        )

    def _good_record(self):
        item = corpus.load_corpus()[0]
        return {
            "item_id": item["item_id"],
            "mode": "forced",
            "invoked_tool": "jackal_calc.anb:mod-pow",
            "raw_stdout": "status=exact r=24\n",
            "parsed_status": "exact",
            "passed": True,
            "refused": False,
            "latency_ms": 7.5,
        }

    def _receipt(self, records=None, **overrides):
        """A complete results object — the only shape that is a receipt."""
        payload = {
            "schema": "jackal-eval-v2-results-v1",
            "mode": "forced",
            "timestamp_utc": "2026-08-19T00:00:00Z",
            "engine_identity": {
                "engine_source_sha256": "0" * 64,
                "artifact_sha256": "1" * 64,
            },
            "corpus_aggregate_digest": corpus.aggregate_digest(corpus.load_corpus()),
            "records": [self._good_record()] if records is None else records,
        }
        payload.update(overrides)
        return payload

    def test_complete_receipt_verifies(self):
        proc = self._run_cli(self._write(self._receipt()))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("RECEIPT_VERIFY_OK", proc.stdout)
        self.assertIn("corpus_digest_match: True", proc.stdout)
        for name in metrics.METRIC_NAMES:
            self.assertIn(name, proc.stdout)

    def test_each_missing_required_top_level_field_is_rejected(self):
        """One case per required top-level field. This is finding 1's regression."""
        for field in metrics.REQUIRED_RECEIPT_FIELDS:
            payload = self._receipt()
            del payload[field]
            proc = self._run_cli(self._write(payload))
            self.assertNotEqual(
                proc.returncode,
                0,
                f"receipt missing top-level {field!r} was accepted:\n{proc.stdout}",
            )
            self.assertIn("RECEIPT_VERIFY_FAIL", proc.stderr)
            self.assertIn("missing required top-level receipt field(s)", proc.stderr)
            self.assertIn(field, proc.stderr)
            self.assertNotIn("RECEIPT_VERIFY_OK", proc.stdout)

    def test_null_required_top_level_field_is_rejected(self):
        """Present-but-null binds nothing, so it is treated as absent."""
        for field in metrics.REQUIRED_RECEIPT_FIELDS:
            proc = self._run_cli(self._write(self._receipt(**{field: None})))
            self.assertNotEqual(proc.returncode, 0, proc.stdout)
            self.assertIn(field, proc.stderr)

    def test_bare_record_list_is_not_a_receipt(self):
        """The degenerate case: a list of records binds none of the four."""
        proc = self._run_cli(self._write([self._good_record()]))
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertNotIn("RECEIPT_VERIFY_OK", proc.stdout)
        for field in metrics.REQUIRED_RECEIPT_FIELDS:
            self.assertIn(field, proc.stderr)

    def test_missing_receipt_field_report_is_exactly_the_absent_names(self):
        self.assertEqual(metrics.missing_receipt_field_report({}), list(
            metrics.REQUIRED_RECEIPT_FIELDS
        ))
        full = self._receipt()
        self.assertEqual(metrics.missing_receipt_field_report(full), [])
        del full["mode"]
        self.assertEqual(metrics.missing_receipt_field_report(full), ["mode"])

    def test_each_missing_required_record_field_is_rejected(self):
        for field in metrics.REQUIRED_RECORD_FIELDS:
            rec = self._good_record()
            rec.pop(field)
            proc = self._run_cli(self._write(self._receipt([rec])))
            self.assertNotEqual(
                proc.returncode, 0, f"missing {field!r} was accepted:\n{proc.stdout}"
            )
            self.assertIn("RECEIPT_VERIFY_FAIL", proc.stderr)
            self.assertIn(field, proc.stderr)
            self.assertNotIn("RECEIPT_VERIFY_OK", proc.stdout)

    def test_missing_field_report_names_index_and_fields(self):
        rec = self._good_record()
        rec.pop("latency_ms")
        rec.pop("refused")
        bad = metrics.missing_field_report([self._good_record(), rec])
        self.assertEqual(len(bad), 1)
        idx, item_id, miss = bad[0]
        self.assertEqual(idx, 1)
        self.assertEqual(item_id, rec["item_id"])
        self.assertEqual(sorted(miss), ["latency_ms", "refused"])

    def test_unknown_item_id_is_rejected(self):
        rec = self._good_record()
        rec["item_id"] = "not.a.corpus.item.v1"
        proc = self._run_cli(self._write(self._receipt([rec])))
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("RECEIPT_VERIFY_FAIL", proc.stderr)

    def test_stale_corpus_digest_is_rejected(self):
        proc = self._run_cli(
            self._write(self._receipt(corpus_aggregate_digest="0" * 64))
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("does not bind to this corpus", proc.stderr)

    def test_unrankable_status_token_is_refused_by_the_cli(self):
        rec = self._good_record()
        rec["parsed_status"] = "vibes-exact"
        proc = self._run_cli(self._write(self._receipt([rec])))
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("not on the registry assurance axis", proc.stderr)

    def test_real_runner_receipt_from_this_repo_verifies(self):
        """A receipt shaped exactly as runner.py writes one, incl. structural-exact.

        This is finding 3's regression at the CLI layer: before
        `structural-exact` had a place on the axis, the first receipt containing a
        `test-exists` record made this exit non-zero with a ValueError.
        """
        struct = [
            it
            for it in corpus.load_corpus()
            if it["expected"].get("status") == "structural-exact"
        ]
        self.assertTrue(struct, "no corpus item exercises structural-exact")
        records = [
            {
                "item_id": it["item_id"],
                "mode": "forced",
                "invoked_tool": f"jackal_calc.anb:{it['argv'][0]}",
                "raw_stdout": "status=structural-exact\nconsequence=informational\n",
                "parsed_status": "structural-exact",
                "passed": True,
                "refused": False,
                "latency_ms": 3.5,
            }
            for it in struct
        ]
        proc = self._run_cli(self._write(self._receipt(records)))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("RECEIPT_VERIFY_OK", proc.stdout)
        self.assertIn("false_strong_claim_rate = 0.000000", proc.stdout)


class RunnerContract(unittest.TestCase):
    """Runner scoring and refusal detection, without building the engine."""

    def setUp(self):
        import runner

        self.runner = runner

    def test_no_model_api_is_referenced(self):
        text = (V2 / "runner.py").read_text(encoding="utf-8")
        self.assertIn("NO MODEL IS INVOKED BY THIS FILE", text)
        for forbidden in ("openai", "anthropic", "requests.post", "urllib.request"):
            self.assertNotIn(forbidden, text.lower().replace("_", ""))

    def test_panic_is_refused_even_on_zero_exit(self):
        item = {
            "item_id": "x",
            "expected": {"refused": True, "reason_contains": "crt-not-coprime"},
        }
        passed, refused, reason, _ = self.runner.score(
            item, 0, "", "ANUBIS_PANIC: crt: moduli are not pairwise coprime "
            "(crt-not-coprime)"
        )
        self.assertTrue(refused)
        self.assertTrue(passed)
        self.assertIn("crt-not-coprime", reason)

    def test_nonzero_exit_is_refused(self):
        item = {"item_id": "x", "expected": {"status": "exact"}}
        passed, refused, _, notes = self.runner.score(item, 101, "", "")
        self.assertTrue(refused)
        self.assertFalse(passed)
        self.assertTrue(any("unexpected refusal" in n for n in notes))

    def test_wrong_refusal_reason_fails(self):
        item = {
            "item_id": "x",
            "expected": {"refused": True, "reason_contains": "mod-inv-not-coprime"},
        }
        passed, _, _, notes = self.runner.score(
            item, 101, "", "ANUBIS_PANIC: wrong number of arguments"
        )
        self.assertFalse(passed)
        self.assertTrue(any("reason missing" in n for n in notes))

    def test_status_parsed_with_equals_and_with_space(self):
        self.assertEqual(self.runner.parse_status("status=exact r=24"), "exact")
        self.assertEqual(
            self.runner.parse_status("jackal-eval-cert v2\nstatus bounded\nend"),
            "bounded",
        )
        self.assertIsNone(self.runner.parse_status("13835058055282163712"))

    def test_enclosure_containment_is_the_check_not_equality(self):
        item = {
            "item_id": "x",
            "expected": {"status": "bounded", "encloses": ["0", "1"]},
        }
        wide = "status=bounded range-enclosure=[-0.5,1.5]"
        self.assertTrue(self.runner.score(item, 0, wide, "")[0])
        narrow = "status=bounded range-enclosure=[0.25,0.75]"
        passed, _, _, notes = self.runner.score(item, 0, narrow, "")
        self.assertFalse(passed)
        self.assertTrue(any("does not contain" in n for n in notes))

    def test_bare_value_item_requires_exact_stdout(self):
        item = {
            "item_id": "x",
            "expected": {"status": None, "stdout_equals": "13835058055282163712"},
        }
        self.assertTrue(self.runner.score(item, 0, "13835058055282163712\n", "")[0])
        passed, _, _, notes = self.runner.score(item, 0, "4611686018427387904\n", "")
        self.assertFalse(passed)
        self.assertTrue(any("stdout: want" in n for n in notes))

    def test_status_none_means_no_status_token_allowed(self):
        item = {"item_id": "x", "expected": {"status": None}}
        self.assertTrue(self.runner.score(item, 0, "36\n", "")[0])
        passed, _, _, notes = self.runner.score(item, 0, "status=exact r=36\n", "")
        self.assertFalse(passed)
        self.assertTrue(any("status: want None" in n for n in notes))


if __name__ == "__main__":
    unittest.main(verbosity=2)
