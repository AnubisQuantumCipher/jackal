#!/usr/bin/env python3
"""Contract tests for `tools/eval_v2_gate.py`.

The gate under test turns the three requirements in `evals/v2/protocol.md` lines
188-200 into a verdict. These tests never invoke a model and never build
`jackal_calc.anb`: every results file is synthetic, written under
`tempfile.mkdtemp`, and every rate is a ratio of rows this file constructs.

What they defend:

  a) the three-valued verdict. `NOT_MEASURABLE` is a distinct verdict with a
     distinct exit code (3) and a distinct token, and it is reached for the four
     inputs that cannot support a verdict: forced-mode verifier use (1.0 by
     construction), autonomous mode with no transcript (0.0 because nothing was
     supplied), an empty eligible denominator (`None`, which is undefined and NOT
     1.0), and a receipt that does not bind to this corpus;
  b) the threshold. `>=` at exactly 0.90 passes, one representable step below
     fails, and the constant equals the number `protocol.md` line 192 writes;
  c) requirement 2 in BOTH modes: a count of 1 is a FAIL in forced mode as well
     as autonomous, and a 0 over rows on which the detector could not have moved
     is `no-downgrade-observable-rows`, not PASS;
  d) requirement 3 by delegation: the gate surfaces a nonzero
     `tools/profile_verify.py` exit as FAIL, proved on a temp-copied profile tree
     with a deliberately dropped tool. The real profile files are never mutated;
  e) NON-VACUITY. The gate can be made to fail by a targeted perturbation of a
     receipt that passes today, and by raising only the threshold constant. A
     gate that cannot be made to fail is not discriminating.

Run: python3 -m unittest tests.eval_v2_gate_test -v
"""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "tools" / "eval_v2_gate.py"
PROFILE_VERIFY = ROOT / "tools" / "profile_verify.py"
PROTOCOL = ROOT / "evals" / "v2" / "protocol.md"
PROFILE_DIR = Path("plugin") / "hermes" / "profiles"
SCHEMA_PATH = Path("plugin") / "hermes" / "schemas" / "jackal_agent_profile.schema.json"
TOOLS_PATH = Path("plugin") / "hermes" / "tools.json"

sys.path.insert(0, str(ROOT / "evals" / "v2"))
import corpus as v2_corpus  # noqa: E402
import metrics as v2_metrics  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - import plumbing
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: `@dataclass` resolves `cls.__module__` through
    # `sys.modules` and raises AttributeError if the module is not there yet.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


GATE = load_module("eval_v2_gate", GATE_PATH)
VERIFY = load_module("profile_verify", PROFILE_VERIFY)

FRONT_DOOR = "jackal_verify_bundle"
FULL_PROFILE_DIGEST = GATE.profile_tools(ROOT, "full")[1]


# ---------------------------------------------------------------------------
# synthetic corpora and receipts
# ---------------------------------------------------------------------------


def synthetic_corpus(
    eligible: int,
    ineligible: int = 0,
    requested_status: str | None = "exact",
) -> list[dict[str, Any]]:
    """A corpus whose eligible denominator is exactly `eligible`.

    The denominator has to be chosen, not inherited: the frozen v2 corpus has 19
    eligible items, so rates like 0.95 are not representable over it. Every rate
    in this file states the ratio it was built from.
    """
    items = []
    for i in range(eligible + ineligible):
        items.append(
            {
                "item_id": f"syn.item.{i:04d}.v1",
                "question": f"synthetic question {i}",
                "argv": ["synthetic", str(i)],
                "expected": {
                    "evidence_status": "exact",
                    "requested_status": requested_status,
                    "consequence_ceiling": "decision-boundary",
                },
                "eligible_for_verifier": i < eligible,
                "category": "exact_integer",
            }
        )
    return items


def record(
    item_id: str,
    *,
    mode: str,
    invoked_tool: str = "",
    parsed_status: str | None = "exact",
    passed: bool = True,
    refused: bool = False,
    latency_ms: float = 5.0,
    **extra: Any,
) -> dict[str, Any]:
    row = {
        "item_id": item_id,
        "mode": mode,
        "invoked_tool": invoked_tool,
        "raw_stdout": f"status={parsed_status}\n" if parsed_status else "",
        "parsed_status": parsed_status,
        "passed": passed,
        "refused": refused,
        "latency_ms": latency_ms,
    }
    row.update(extra)
    return row


def rows_for(
    items: list[dict[str, Any]],
    *,
    mode: str,
    front_door_rows: int = 0,
    tool_rows: int = 0,
    tool_name: str = "jackal_mod_pow",
    invocation_ok: bool | None = True,
) -> list[dict[str, Any]]:
    """One row per item. The first `front_door_rows` ELIGIBLE rows call a front
    door; the next `tool_rows` eligible rows call some other tool."""
    out = []
    front_left, other_left = front_door_rows, tool_rows
    for item in items:
        tool = ""
        extra: dict[str, Any] = {}
        if item["eligible_for_verifier"] and front_left > 0:
            tool = FRONT_DOOR
            front_left -= 1
            if invocation_ok is not None:
                extra["verifier_invocation_ok"] = invocation_ok
        elif item["eligible_for_verifier"] and other_left > 0:
            tool = tool_name
            other_left -= 1
        elif mode == "forced":
            tool = f"jackal_calc.anb:{item['argv'][0]}"
        out.append(record(item["item_id"], mode=mode, invoked_tool=tool, **extra))
    return out


class ReceiptWriter:
    """Writes synthetic receipts to a temp dir that is removed on cleanup."""

    def __init__(self, test: unittest.TestCase):
        self.dir = Path(tempfile.mkdtemp(prefix="jackal-eval-v2-gate-"))
        test.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self._n = 0

    def write(
        self,
        items: list[dict[str, Any]],
        records: list[dict[str, Any]],
        *,
        mode: str,
        transcript: str | None = None,
        profile: str | None = None,
        profile_digest: str | None = None,
        drop: tuple[str, ...] = (),
        **overrides: Any,
    ) -> str:
        payload: dict[str, Any] = {
            "schema": "jackal-eval-v2-results-v1",
            "mode": mode,
            "timestamp_utc": "2026-08-19T00:00:00Z",
            "corpus_item_count": len(items),
            "items_run": len(records),
            "corpus_aggregate_digest": v2_corpus.aggregate_digest(items),
            "engine_identity": {
                "engine_source_sha256": "0" * 64,
                "artifact_sha256": "1" * 64,
                "build": "synthetic",
            },
            "transcript_path": transcript,
            "model_invoked": False,
            "records": records,
        }
        if profile is not None:
            payload["profile_id"] = profile
            payload["profile_digest_sha256"] = (
                FULL_PROFILE_DIGEST if profile_digest is None else profile_digest
            )
        payload.update(overrides)
        for key in drop:
            payload.pop(key, None)
        self._n += 1
        path = self.dir / f"results-{self._n:02d}.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return str(path)


class GateCase(unittest.TestCase):
    """Shared assertions. Every reason a finding reports must be a declared class."""

    def setUp(self) -> None:
        self.receipts = ReceiptWriter(self)

    def finding(self, summary: dict[str, Any], requirement: str) -> dict[str, Any]:
        for f in summary["findings"]:
            if f["requirement"] == requirement:
                self.assertIn(
                    f["reason"],
                    ("-",) + GATE.REASON_CLASSES,
                    f"{requirement} reported an undeclared reason class",
                )
                return f
        self.fail(f"no {requirement} finding in {summary['findings']}")

    def assertVerdict(
        self, summary: dict[str, Any], requirement: str, verdict: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        found = self.finding(summary, requirement)
        self.assertEqual(
            found["verdict"], verdict,
            f"{requirement}: {found['verdict']} reason={found['reason']} "
            f"detail={found['detail']}",
        )
        if reason is not None:
            self.assertEqual(found["reason"], reason, found["detail"])
        return found


# ---------------------------------------------------------------------------
# the gate is pinned to the authority, not to a paraphrase of it
# ---------------------------------------------------------------------------


class AuthorityIsQuoted(GateCase):
    def test_requirements_block_is_quoted_verbatim_in_the_gate(self) -> None:
        """Every non-blank line of protocol.md 188-200 appears in the docstring.

        If the authority is edited, this test fails rather than letting the gate
        enforce a superseded requirement.
        """
        lines = PROTOCOL.read_text(encoding="utf-8").splitlines()[187:200]
        doc = GATE.__doc__ or ""
        self.assertTrue(lines[0].startswith("## Requirements"), lines[0])
        for line in lines:
            if line.strip():
                self.assertIn(line.strip(), doc, f"not quoted: {line!r}")

    def test_threshold_constant_equals_the_number_protocol_line_192_writes(self) -> None:
        line = PROTOCOL.read_text(encoding="utf-8").splitlines()[191]
        match = re.search(r"verifier_use_rate\s*>=\s*([0-9.]+)", line)
        self.assertIsNotNone(match, line)
        self.assertEqual(
            GATE.VERIFIER_USE_RATE_MIN, Fraction(Decimal(match.group(1)))
        )
        self.assertEqual(GATE.VERIFIER_USE_RATE_MIN, Fraction(9, 10))

    def test_downgrade_constant_equals_protocol_line_193(self) -> None:
        line = PROTOCOL.read_text(encoding="utf-8").splitlines()[192]
        self.assertIn("silent_downgrade_count == 0", line)
        self.assertEqual(GATE.SILENT_DOWNGRADE_MAX, 0)

    def test_front_doors_are_the_two_protocol_names(self) -> None:
        """protocol.md lines 141-142 name the two verification front doors."""
        sentence = " ".join(
            PROTOCOL.read_text(encoding="utf-8").splitlines()[140:142]
        )
        for name in GATE.VERIFIER_FRONT_DOORS:
            self.assertIn(name, sentence)
        self.assertIn("verification front door", sentence)
        surface = GATE.declared_tool_names(ROOT)
        for name in GATE.VERIFIER_FRONT_DOORS:
            self.assertIn(name, surface, "front door absent from the tool surface")

    def test_three_verdicts_have_three_distinct_tokens_and_exit_codes(self) -> None:
        self.assertEqual(
            GATE.VERDICT_TOKEN,
            {
                "PASS": "EVAL_V2_GATE_PASS",
                "FAIL": "EVAL_V2_GATE_FAIL",
                "NOT_MEASURABLE": "EVAL_V2_GATE_NOT_MEASURABLE",
            },
        )
        self.assertEqual(GATE.EXIT_CODE, {"PASS": 0, "FAIL": 1, "NOT_MEASURABLE": 3})
        self.assertEqual(len(set(GATE.EXIT_CODE.values())), 3)


# ---------------------------------------------------------------------------
# requirement 1 — the threshold, measured
# ---------------------------------------------------------------------------


class Requirement1Threshold(GateCase):
    """Table-driven: each row states the ratio it was constructed from."""

    def _summary(
        self, eligible: int, front_door: int, *, ineligible: int = 0
    ) -> dict[str, Any]:
        items = synthetic_corpus(eligible, ineligible)
        rows = rows_for(items, mode="autonomous", front_door_rows=front_door,
                        tool_rows=eligible - front_door)
        path = self.receipts.write(
            items, rows, mode="autonomous", transcript="/tmp/live-session.json",
            profile="full",
        )
        forced = self.receipts.write(
            items, rows_for(items, mode="forced"), mode="forced",
        )
        return GATE.evaluate([path, forced], root=ROOT, corpus_items=items)

    def test_rate_table(self) -> None:
        cases = [
            # (name, eligible, front_door, exact ratio, verdict)
            ("0.95 = 19/20", 20, 19, Fraction(19, 20), GATE.PASS),
            ("0.85 = 17/20", 20, 17, Fraction(17, 20), GATE.FAIL),
            ("exactly 0.90 = 18/20", 20, 18, Fraction(18, 20), GATE.PASS),
            ("exactly 0.90 = 27/30", 30, 27, Fraction(27, 30), GATE.PASS),
            # One row below the threshold at a 1000-row denominator: 899/1000 is
            # the largest ratio strictly below 9/10 that this denominator can
            # represent, i.e. one representable step below the requirement.
            ("0.899 = 899/1000", 1000, 899, Fraction(899, 1000), GATE.FAIL),
            ("0.900 = 900/1000", 1000, 900, Fraction(900, 1000), GATE.PASS),
        ]
        for name, eligible, front_door, ratio, verdict in cases:
            with self.subTest(name):
                self.assertEqual(Fraction(front_door, eligible), ratio)
                summary = self._summary(eligible, front_door)
                found = self.assertVerdict(summary, "req1", verdict)
                self.assertIn(f"({front_door}/{eligible})", found["observed"])
                if verdict == GATE.PASS:
                    self.assertEqual(summary["verdict"], GATE.PASS)
                    self.assertEqual(summary["exit_code"], 0)
                else:
                    self.assertEqual(found["reason"],
                                     "verifier-use-rate-below-threshold")
                    self.assertEqual(summary["exit_code"], 1)

    def test_fail_names_the_threshold_and_prints_observed_versus_required(self) -> None:
        summary = self._summary(20, 17)
        found = self.assertVerdict(summary, "req1", GATE.FAIL,
                                  "verifier-use-rate-below-threshold")
        self.assertIn("0.850000", found["detail"])
        self.assertIn("0.90", found["detail"])
        self.assertIn("17/20", found["detail"])
        self.assertIn("0.850000 (17/20)", found["observed"])
        self.assertIn("0.90", found["required"])
        self.assertIn("n_eligible=20", found["observed"])

    def test_boundary_is_inclusive_and_one_float_step_below_is_not(self) -> None:
        """The comparison is exact, so the boundary does not turn on rounding.

        `18/20` is the row-granular boundary; `math.nextafter(0.9, 0.0)` is the
        largest IEEE-754 double strictly below 0.9, i.e. the smallest step below
        the threshold that a float can represent at all. `Fraction` compares
        against a float exactly, so neither direction is decided by a rounding.
        """
        self.assertTrue(Fraction(18, 20) >= GATE.VERIFIER_USE_RATE_MIN)
        self.assertTrue(Fraction(27, 30) >= GATE.VERIFIER_USE_RATE_MIN)
        self.assertFalse(Fraction(899, 1000) >= GATE.VERIFIER_USE_RATE_MIN)
        just_below = math.nextafter(0.9, 0.0)
        self.assertLess(just_below, 0.9)
        self.assertFalse(just_below >= GATE.VERIFIER_USE_RATE_MIN)
        self.assertTrue(0.9 >= GATE.VERIFIER_USE_RATE_MIN)


# ---------------------------------------------------------------------------
# requirement 1 — the four inputs that cannot support a verdict
# ---------------------------------------------------------------------------


class Requirement1NotMeasurable(GateCase):
    def test_autonomous_with_no_transcript_is_not_a_failure(self) -> None:
        """THE load-bearing case. rate 0.0 with no transcript is not a miss."""
        items = synthetic_corpus(20)
        rows = rows_for(items, mode="autonomous")  # every invoked_tool empty
        path = self.receipts.write(items, rows, mode="autonomous", transcript=None,
                                   profile="full")
        summary = GATE.evaluate([path], root=ROOT, corpus_items=items)

        found = self.assertVerdict(summary, "req1", GATE.NOT_MEASURABLE,
                                   "no-transcript-supplied")
        self.assertNotEqual(found["verdict"], GATE.FAIL)
        self.assertNotEqual(found["verdict"], GATE.PASS)
        # metrics.py really does read 0.0 here — the gate is not dodging a number.
        self.assertEqual(
            v2_metrics.compute_metrics(rows, items)["verifier_use_rate"], 0.0
        )
        self.assertIn("0.000000", found["observed"])
        detail = found["detail"].lower()
        self.assertIn("no transcript", detail)
        self.assertIn("declined", detail)  # named only to be ruled out
        self.assertRegex(found["detail"], r"NOT that the model declined")
        # And the whole-gate verdict is the third one, not a pass and not a fail.
        self.assertEqual(summary["verdict"], GATE.NOT_MEASURABLE)
        self.assertEqual(summary["exit_code"], 3)

    def test_forced_mode_rate_one_is_not_requirement_one_satisfied(self) -> None:
        items = synthetic_corpus(20)
        rows = rows_for(items, mode="forced")
        path = self.receipts.write(items, rows, mode="forced")
        # metrics.py reads 1.0 here, by construction.
        self.assertEqual(
            v2_metrics.compute_metrics(rows, items)["verifier_use_rate"], 1.0
        )
        summary = GATE.evaluate([path], root=ROOT, corpus_items=items)
        found = self.assertVerdict(summary, "req1", GATE.NOT_MEASURABLE,
                                   "forced-mode-verifier-use-by-construction")
        self.assertIn("by construction", found["detail"])
        self.assertIn("1.000000", found["observed"])
        self.assertNotEqual(found["verdict"], GATE.PASS)
        self.assertEqual(summary["exit_code"], 3)

    def test_forced_mode_still_enforces_requirement_two(self) -> None:
        """Requirement 1 is unmeasurable in forced mode; requirement 2 is not."""
        items = synthetic_corpus(20)
        clean = self.receipts.write(items, rows_for(items, mode="forced"),
                                    mode="forced")
        report = GATE.admit_receipt(clean, items)
        self.assertTrue(report.admitted, report.admission_detail)
        self.assertEqual(GATE.check_silent_downgrade(report).verdict, GATE.PASS)

    def test_none_metric_is_not_measurable_and_is_never_read_as_one(self) -> None:
        items = synthetic_corpus(0, ineligible=6)
        rows = rows_for(items, mode="autonomous")
        path = self.receipts.write(items, rows, mode="autonomous",
                                   transcript="/tmp/live-session.json",
                                   profile="full")
        # metrics.py returns None, not 1.0, on the empty denominator.
        self.assertIsNone(
            v2_metrics.compute_metrics(rows, items)["verifier_use_rate"]
        )
        summary = GATE.evaluate([path], root=ROOT, corpus_items=items)
        found = self.assertVerdict(summary, "req1", GATE.NOT_MEASURABLE,
                                   "empty-eligible-denominator")
        self.assertNotEqual(found["verdict"], GATE.PASS)
        self.assertIn("None", found["observed"])
        self.assertIn("n_eligible=0", found["observed"])
        self.assertIn("NOT 1.0", found["detail"])
        self.assertNotIn("1.000000", found["observed"])

    def test_missing_profile_identity_is_not_measurable(self) -> None:
        """protocol.md line 190 scopes the requirement to a named profile."""
        items = synthetic_corpus(20)
        rows = rows_for(items, mode="autonomous", front_door_rows=20)
        path = self.receipts.write(items, rows, mode="autonomous",
                                   transcript="/tmp/live-session.json")
        summary = GATE.evaluate([path], root=ROOT, corpus_items=items)
        self.assertVerdict(summary, "req1", GATE.NOT_MEASURABLE,
                           "profile-identity-absent")

    def test_wrong_profile_digest_is_not_measurable(self) -> None:
        items = synthetic_corpus(20)
        rows = rows_for(items, mode="autonomous", front_door_rows=20)
        path = self.receipts.write(items, rows, mode="autonomous",
                                   transcript="/tmp/live-session.json",
                                   profile="full", profile_digest="f" * 64)
        summary = GATE.evaluate([path], root=ROOT, corpus_items=items)
        found = self.assertVerdict(summary, "req1", GATE.NOT_MEASURABLE,
                                   "profile-identity-mismatch")
        self.assertIn(FULL_PROFILE_DIGEST, found["detail"])

    def test_core_profile_exposes_a_front_door_so_scope_check_passes(self) -> None:
        """Instrument check on the scope test itself: a valid profile passes it."""
        items = synthetic_corpus(20)
        rows = rows_for(items, mode="autonomous", front_door_rows=19)
        path = self.receipts.write(
            items, rows, mode="autonomous", transcript="/tmp/live.json",
            profile="core", profile_digest=GATE.profile_tools(ROOT, "core")[1],
        )
        summary = GATE.evaluate([path], root=ROOT, corpus_items=items)
        found = self.finding(summary, "req1")
        self.assertEqual(found["verdict"], GATE.PASS, found["detail"])
        self.assertIn("profile=core", found["detail"])


# ---------------------------------------------------------------------------
# requirement 1 — numerator honesty
# ---------------------------------------------------------------------------


class Requirement1Numerator(GateCase):
    def _autonomous(self, items, rows) -> dict[str, Any]:
        path = self.receipts.write(items, rows, mode="autonomous",
                                   transcript="/tmp/live-session.json",
                                   profile="full")
        return GATE.evaluate([path], root=ROOT, corpus_items=items)

    def test_non_front_door_tool_calls_do_not_count_as_verification(self) -> None:
        """metrics.py counts any tool; protocol.md lines 140-142 count two names.

        The verdict is taken on the protocol's numerator, so a transcript in which
        the model called something else on every row is a MISS, not a 1.0.
        """
        items = synthetic_corpus(20)
        rows = rows_for(items, mode="autonomous", front_door_rows=0, tool_rows=20)
        self.assertEqual(
            v2_metrics.compute_metrics(rows, items)["verifier_use_rate"], 1.0
        )
        summary = self._autonomous(items, rows)
        found = self.assertVerdict(summary, "req1", GATE.FAIL,
                                   "verifier-use-rate-below-threshold")
        self.assertIn("0.000000 (0/20)", found["observed"])
        self.assertTrue(
            any("metrics-numerator-broader-than-protocol" in n
                for n in found["notes"]),
            found["notes"],
        )

    def test_underscore_suffixed_lookalike_is_not_a_front_door(self) -> None:
        self.assertTrue(GATE.names_front_door("jackal_verify_bundle"))
        self.assertTrue(GATE.names_front_door("tool:jackal_verify_receipt(args)"))
        self.assertFalse(GATE.names_front_door("jackal_verify_bundle_v2"))
        self.assertFalse(GATE.names_front_door("xjackal_verify_bundle"))
        self.assertFalse(GATE.names_front_door("jackal_verify"))
        self.assertFalse(GATE.names_front_door(""))
        self.assertFalse(GATE.names_front_door(None))

    def test_errored_invocation_is_not_counted_as_use(self) -> None:
        """protocol.md line 148: an invocation that errored is not use."""
        items = synthetic_corpus(20)
        rows = rows_for(items, mode="autonomous", front_door_rows=20,
                        invocation_ok=False)
        summary = self._autonomous(items, rows)
        found = self.assertVerdict(summary, "req1", GATE.FAIL,
                                   "verifier-use-rate-below-threshold")
        self.assertIn("0.000000 (0/20)", found["observed"])
        self.assertTrue(
            any("verifier_invocation_ok=false" in n for n in found["notes"]),
            found["notes"],
        )

    def test_unrecorded_invocation_result_is_counted_but_disclosed(self) -> None:
        items = synthetic_corpus(20)
        rows = rows_for(items, mode="autonomous", front_door_rows=19,
                        tool_rows=1, invocation_ok=None)
        summary = self._autonomous(items, rows)
        found = self.assertVerdict(summary, "req1", GATE.PASS)
        self.assertTrue(
            any("invocation-result-unrecorded" in n for n in found["notes"]),
            found["notes"],
        )

    def test_human_supplied_transcript_provenance_is_disclosed(self) -> None:
        items = synthetic_corpus(20)
        rows = rows_for(items, mode="autonomous", front_door_rows=19, tool_rows=1)
        found = self.finding(self._autonomous(items, rows), "req1")
        self.assertEqual(found["verdict"], GATE.PASS)
        self.assertTrue(
            any("model_invoked=False" in n for n in found["notes"]), found["notes"]
        )

    def test_metric_arithmetic_disagreement_refuses_rather_than_scores(self) -> None:
        """The gate's second counting site is guarded, not trusted."""
        items = synthetic_corpus(20)
        rows = rows_for(items, mode="autonomous", front_door_rows=19, tool_rows=1)
        path = self.receipts.write(items, rows, mode="autonomous",
                                   transcript="/tmp/live.json", profile="full")
        report = GATE.admit_receipt(path, items)
        self.assertTrue(report.admitted, report.admission_detail)
        # Agreement first: the gate's own count reproduces metrics.py exactly.
        self.assertEqual(
            report.counts.used_any_tool / report.counts.denominator,
            report.metrics["verifier_use_rate"],
        )
        self.assertEqual(GATE.check_verifier_use_rate(report, ROOT).verdict,
                         GATE.PASS)
        # Now part the two sites and require a refusal, not a score.
        report.metrics = dict(report.metrics, verifier_use_rate=0.5)
        found = GATE.check_verifier_use_rate(report, ROOT)
        self.assertEqual(found.verdict, GATE.NOT_MEASURABLE)
        self.assertEqual(found.reason, "metric-arithmetic-disagreement")


# ---------------------------------------------------------------------------
# requirement 2
# ---------------------------------------------------------------------------


class Requirement2(GateCase):
    def _downgrade_corpus(self) -> list[dict[str, Any]]:
        items = synthetic_corpus(4)
        # One item asks for a strictly stronger lane than its row will return.
        items[0]["expected"]["requested_status"] = "formal-bounded"
        return items

    def _rows(self, items, mode) -> list[dict[str, Any]]:
        rows = rows_for(items, mode=mode, front_door_rows=4)
        rows[0]["parsed_status"] = "bounded"
        rows[0]["raw_stdout"] = "status=bounded\n"
        return rows

    def test_one_downgrade_fails_in_both_modes(self) -> None:
        for mode in ("forced", "autonomous"):
            with self.subTest(mode):
                items = self._downgrade_corpus()
                rows = self._rows(items, mode)
                self.assertEqual(
                    v2_metrics.compute_metrics(rows, items)["silent_downgrade_count"],
                    1,
                )
                path = self.receipts.write(
                    items, rows, mode=mode,
                    transcript="/tmp/live.json" if mode == "autonomous" else None,
                    profile="full" if mode == "autonomous" else None,
                )
                summary = GATE.evaluate([path], root=ROOT, corpus_items=items)
                found = self.assertVerdict(summary, "req2", GATE.FAIL,
                                          "silent-downgrade-detected")
                self.assertIn("silent_downgrade_count = 1", found["observed"])
                self.assertIn(f"mode={mode}", found["observed"])
                # An absolute count, never softened into a rate.
                self.assertNotIn("%", found["observed"])
                self.assertIn("not converted to a rate", found["detail"])
                # FAIL outranks any NOT_MEASURABLE sibling.
                self.assertEqual(summary["verdict"], GATE.FAIL)
                self.assertEqual(summary["exit_code"], 1)

    def test_zero_over_observable_rows_passes_per_receipt(self) -> None:
        for mode in ("forced", "autonomous"):
            with self.subTest(mode):
                items = synthetic_corpus(4)
                path = self.receipts.write(items, rows_for(items, mode=mode),
                                           mode=mode)
                report = GATE.admit_receipt(path, items)
                found = GATE.check_silent_downgrade(report)
                self.assertEqual(found.verdict, GATE.PASS, found.detail)
                self.assertIn("rows_a_downgrade_could_register_on=4",
                              found.observed)

    def test_vacuous_zero_is_not_measurable(self) -> None:
        """A 0 the detector could not have moved is not evidence of a 0."""
        items = synthetic_corpus(4, requested_status=None)
        path = self.receipts.write(items, rows_for(items, mode="forced"),
                                   mode="forced")
        report = GATE.admit_receipt(path, items)
        self.assertEqual(report.metrics["silent_downgrade_count"], 0)
        found = GATE.check_silent_downgrade(report)
        self.assertEqual(found.verdict, GATE.NOT_MEASURABLE)
        self.assertEqual(found.reason, "no-downgrade-observable-rows")
        self.assertIn("rows_a_downgrade_could_register_on=0", found.observed)

    def test_one_mode_only_cannot_discharge_both_modes(self) -> None:
        items = synthetic_corpus(4)
        path = self.receipts.write(items, rows_for(items, mode="forced"),
                                   mode="forced")
        summary = GATE.evaluate([path], root=ROOT, corpus_items=items)
        found = self.assertVerdict(summary, "req2", GATE.NOT_MEASURABLE,
                                   "mode-not-covered")
        self.assertIn("autonomous", found["detail"])

    def test_both_modes_supplied_discharges_requirement_two(self) -> None:
        items = synthetic_corpus(20)
        forced = self.receipts.write(items, rows_for(items, mode="forced"),
                                     mode="forced")
        auto = self.receipts.write(
            items, rows_for(items, mode="autonomous", front_door_rows=19,
                            tool_rows=1),
            mode="autonomous", transcript="/tmp/live.json", profile="full",
        )
        summary = GATE.evaluate([forced, auto], root=ROOT, corpus_items=items)
        self.assertVerdict(summary, "req2", GATE.PASS)
        self.assertVerdict(summary, "req1", GATE.PASS)
        self.assertVerdict(summary, "req3", GATE.PASS)
        self.assertEqual(summary["verdict"], GATE.PASS)
        self.assertEqual(summary["exit_code"], 0)


# ---------------------------------------------------------------------------
# requirement 3
# ---------------------------------------------------------------------------


class ProfileFixture:
    """A throwaway copy of the profile surface. The real files are never touched."""

    def __init__(self, test: unittest.TestCase,
                 mutate: Callable[[dict[str, Any], dict[str, dict[str, Any]]], None]
                 | None = None,
                 reseal: bool = True):
        self.root = Path(tempfile.mkdtemp(prefix="jackal-gate-profile-"))
        test.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / PROFILE_DIR).mkdir(parents=True)
        (self.root / SCHEMA_PATH).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / SCHEMA_PATH, self.root / SCHEMA_PATH)
        tools = json.loads((ROOT / TOOLS_PATH).read_text(encoding="utf-8"))
        profiles = {
            pid: copy.deepcopy(
                json.loads((ROOT / PROFILE_DIR / f"{pid}.json").read_text("utf-8"))
            )
            for pid in ("core", "formal", "full")
        }
        if mutate is not None:
            mutate(tools, profiles)
            if reseal:
                for document in profiles.values():
                    document["profile_digest_sha256"] = VERIFY.profile_digest(document)
        (self.root / TOOLS_PATH).write_text(
            json.dumps(tools, indent=2) + "\n", encoding="utf-8"
        )
        for pid, document in profiles.items():
            (self.root / PROFILE_DIR / f"{pid}.json").write_text(
                json.dumps(document, indent=2) + "\n", encoding="utf-8"
            )


class Requirement3(GateCase):
    def test_real_profile_verify_exits_zero_today(self) -> None:
        """The positive case is the real enforcer on the real files."""
        proc = subprocess.run(
            [sys.executable, str(PROFILE_VERIFY)], capture_output=True, text=True,
            cwd=str(ROOT), timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("profile_verification=verified", proc.stdout)

    def test_gate_reports_pass_on_the_real_tree(self) -> None:
        found = GATE.check_profile_parity(ROOT)
        self.assertEqual(found.verdict, GATE.PASS, found.detail)
        self.assertIn("exit=0", found.observed)

    def test_unmutated_temp_copy_passes(self) -> None:
        """Instrument check: the refusal cases below are not broken fixtures."""
        fixture = ProfileFixture(self)
        found = GATE.check_profile_parity(fixture.root)
        self.assertEqual(found.verdict, GATE.PASS, found.detail)

    def test_dropped_tool_from_tools_json_is_a_fail(self) -> None:
        dropped: list[str] = []

        def mutate(tools, profiles):
            dropped.append(tools["tools"].pop()["name"])

        fixture = ProfileFixture(self, mutate)
        found = GATE.check_profile_parity(fixture.root)
        self.assertEqual(found.verdict, GATE.FAIL)
        self.assertEqual(found.reason, "profile-parity-refused")
        self.assertIn("exit=1", found.observed)
        self.assertIn(dropped[0], found.detail)

    def test_dropped_tool_from_full_profile_is_a_parity_fail(self) -> None:
        def mutate(tools, profiles):
            profiles["full"]["tools"].pop()

        fixture = ProfileFixture(self, mutate)  # resealed, so the digest is valid
        found = GATE.check_profile_parity(fixture.root)
        self.assertEqual(found.verdict, GATE.FAIL)
        self.assertEqual(found.reason, "profile-parity-refused")
        self.assertIn("full-incomplete", found.detail)

    def test_requirement_three_fail_dominates_the_whole_gate(self) -> None:
        def mutate(tools, profiles):
            profiles["full"]["tools"].pop()

        fixture = ProfileFixture(self, mutate)
        items = synthetic_corpus(20)
        forced = self.receipts.write(items, rows_for(items, mode="forced"),
                                     mode="forced")
        auto = self.receipts.write(
            items, rows_for(items, mode="autonomous", front_door_rows=19,
                            tool_rows=1),
            mode="autonomous", transcript="/tmp/live.json", profile="full",
        )
        summary = GATE.evaluate([forced, auto], root=fixture.root,
                                corpus_items=items)
        self.assertVerdict(summary, "req3", GATE.FAIL, "profile-parity-refused")
        self.assertEqual(summary["verdict"], GATE.FAIL)
        self.assertEqual(summary["exit_code"], 1)

    def test_verifier_that_cannot_run_is_not_measurable(self) -> None:
        """A missing profile tree is exit 1 from profile_verify (a refusal); a
        usage-level failure is exit 2 and must NOT be read as a parity verdict."""
        empty = Path(tempfile.mkdtemp(prefix="jackal-gate-empty-"))
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        found = GATE.check_profile_parity(empty)
        self.assertIn(found.verdict, (GATE.FAIL, GATE.NOT_MEASURABLE))
        self.assertNotEqual(found.verdict, GATE.PASS)


# ---------------------------------------------------------------------------
# receipt admission
# ---------------------------------------------------------------------------


class ReceiptAdmission(GateCase):
    def test_each_missing_top_level_field_blocks_requirements_one_and_two(self) -> None:
        items = synthetic_corpus(20)
        rows = rows_for(items, mode="autonomous", front_door_rows=20)
        for field in v2_metrics.REQUIRED_RECEIPT_FIELDS:
            with self.subTest(field):
                path = self.receipts.write(
                    items, rows, mode="autonomous", transcript="/tmp/live.json",
                    profile="full", drop=(field,),
                )
                summary = GATE.evaluate([path], root=ROOT, corpus_items=items)
                for req in ("req1", "req2"):
                    found = self.assertVerdict(summary, req, GATE.NOT_MEASURABLE)
                    self.assertIn(
                        found["reason"],
                        ("receipt-missing-top-level-field", "unknown-mode",
                         "mode-not-covered"),
                    )
                self.assertNotEqual(summary["verdict"], GATE.PASS)

    def test_corpus_digest_mismatch_is_not_measurable(self) -> None:
        items = synthetic_corpus(20)
        rows = rows_for(items, mode="autonomous", front_door_rows=20)
        path = self.receipts.write(items, rows, mode="autonomous",
                                   transcript="/tmp/live.json", profile="full",
                                   corpus_aggregate_digest="0" * 64)
        summary = GATE.evaluate([path], root=ROOT, corpus_items=items)
        self.assertVerdict(summary, "req1", GATE.NOT_MEASURABLE,
                           "corpus-digest-mismatch")

    def test_record_mode_disagreement_is_not_measurable(self) -> None:
        items = synthetic_corpus(4)
        rows = rows_for(items, mode="forced")
        rows[0]["mode"] = "autonomous"
        path = self.receipts.write(items, rows, mode="forced")
        summary = GATE.evaluate([path], root=ROOT, corpus_items=items)
        self.assertVerdict(summary, "req2", GATE.NOT_MEASURABLE,
                           "mode-disagreement")

    def test_record_missing_required_field_is_not_measurable(self) -> None:
        items = synthetic_corpus(4)
        rows = rows_for(items, mode="forced")
        del rows[0]["latency_ms"]
        path = self.receipts.write(items, rows, mode="forced")
        summary = GATE.evaluate([path], root=ROOT, corpus_items=items)
        found = self.assertVerdict(summary, "req2", GATE.NOT_MEASURABLE,
                                   "record-missing-required-field")
        self.assertIn("latency_ms", found["detail"])

    def test_unknown_item_id_is_not_measurable(self) -> None:
        items = synthetic_corpus(4)
        rows = rows_for(items, mode="forced")
        rows[0]["item_id"] = "syn.item.not-in-corpus.v1"
        path = self.receipts.write(items, rows, mode="forced")
        summary = GATE.evaluate([path], root=ROOT, corpus_items=items)
        self.assertVerdict(summary, "req2", GATE.NOT_MEASURABLE,
                           "record-item-not-in-corpus")

    def test_unreadable_results_file_is_not_measurable_not_a_crash(self) -> None:
        path = self.receipts.dir / "not-json.json"
        path.write_text("{ this is not json", encoding="utf-8")
        summary = GATE.evaluate([str(path)], root=ROOT)
        self.assertVerdict(summary, "req1", GATE.NOT_MEASURABLE,
                           "unreadable-results")
        self.assertEqual(summary["exit_code"], 3)

    def test_no_receipt_at_all_still_checks_requirement_three(self) -> None:
        summary = GATE.evaluate([], root=ROOT)
        self.assertVerdict(summary, "req1", GATE.NOT_MEASURABLE,
                           "no-receipt-supplied")
        self.assertVerdict(summary, "req2", GATE.NOT_MEASURABLE,
                           "no-receipt-supplied")
        self.assertVerdict(summary, "req3", GATE.PASS)
        self.assertEqual(summary["exit_code"], 3)


# ---------------------------------------------------------------------------
# NON-VACUITY / instrument control
# ---------------------------------------------------------------------------


class NonVacuityControl(GateCase):
    """Prove the gate can fail. A gate that cannot is not discriminating."""

    def _passing_pair(self, items) -> list[str]:
        forced = self.receipts.write(items, rows_for(items, mode="forced"),
                                     mode="forced")
        auto = self.receipts.write(
            items,
            rows_for(items, mode="autonomous", front_door_rows=19, tool_rows=1),
            mode="autonomous", transcript="/tmp/live.json", profile="full",
        )
        return [forced, auto]

    def test_raising_only_the_threshold_turns_a_pass_into_a_fail(self) -> None:
        items = synthetic_corpus(20)
        paths = self._passing_pair(items)

        baseline = GATE.evaluate(paths, root=ROOT, corpus_items=items)
        self.assertEqual(baseline["verdict"], GATE.PASS)
        self.assertEqual(baseline["exit_code"], 0)
        self.assertIn("0.950000 (19/20)",
                      self.finding(baseline, "req1")["observed"])

        original = GATE.VERIFIER_USE_RATE_MIN
        original_text = GATE.VERIFIER_USE_RATE_MIN_TEXT
        GATE.VERIFIER_USE_RATE_MIN = Fraction(96, 100)  # above the observed 0.95
        GATE.VERIFIER_USE_RATE_MIN_TEXT = "0.96"
        try:
            perturbed = GATE.evaluate(paths, root=ROOT, corpus_items=items)
        finally:
            GATE.VERIFIER_USE_RATE_MIN = original
            GATE.VERIFIER_USE_RATE_MIN_TEXT = original_text

        found = self.assertVerdict(perturbed, "req1", GATE.FAIL,
                                   "verifier-use-rate-below-threshold")
        self.assertIn("0.96", found["detail"])
        self.assertEqual(perturbed["verdict"], GATE.FAIL)
        self.assertEqual(perturbed["exit_code"], 1)
        # And the shipped constant is restored, so the baseline still passes.
        self.assertEqual(
            GATE.evaluate(paths, root=ROOT, corpus_items=items)["exit_code"], 0
        )

    def test_removing_one_front_door_call_turns_a_pass_into_a_fail(self) -> None:
        """The row-level perturbation, with the threshold left alone.

        19/20 = 0.95 passes; 17/20 = 0.85 fails. So the numerator is load-bearing
        and the PASS above is not an artefact of the gate ignoring the rows.
        """
        items = synthetic_corpus(20)
        forced = self.receipts.write(items, rows_for(items, mode="forced"),
                                     mode="forced")
        weakened = self.receipts.write(
            items,
            rows_for(items, mode="autonomous", front_door_rows=17, tool_rows=3),
            mode="autonomous", transcript="/tmp/live.json", profile="full",
        )
        summary = GATE.evaluate([forced, weakened], root=ROOT, corpus_items=items)
        found = self.assertVerdict(summary, "req1", GATE.FAIL,
                                   "verifier-use-rate-below-threshold")
        self.assertIn("0.850000 (17/20)", found["observed"])
        self.assertEqual(summary["exit_code"], 1)

    def test_adding_one_downgrade_turns_a_pass_into_a_fail(self) -> None:
        items = synthetic_corpus(20)
        self.assertEqual(
            GATE.evaluate(self._passing_pair(items), root=ROOT,
                          corpus_items=items)["exit_code"],
            0,
        )
        rows = rows_for(items, mode="forced")
        rows[0]["parsed_status"] = "bounded"  # asked for exact, answered bounded
        rows[0]["raw_stdout"] = "status=bounded\n"
        forced = self.receipts.write(items, rows, mode="forced")
        auto = self.receipts.write(
            items,
            rows_for(items, mode="autonomous", front_door_rows=19, tool_rows=1),
            mode="autonomous", transcript="/tmp/live.json", profile="full",
        )
        summary = GATE.evaluate([forced, auto], root=ROOT, corpus_items=items)
        self.assertVerdict(summary, "req2", GATE.FAIL, "silent-downgrade-detected")
        self.assertEqual(summary["exit_code"], 1)


# ---------------------------------------------------------------------------
# CLI: the exit codes and tokens a caller sees, over the REAL frozen corpus
# ---------------------------------------------------------------------------


class Cli(GateCase):
    """The CLI has no corpus override, so these run against the real 50-item
    corpus: 19 eligible rows, so 18/19 = 0.947368 passes and 17/19 = 0.894737
    fails. Rates that need another denominator are covered above through
    `evaluate(corpus_items=...)`."""

    def setUp(self) -> None:
        super().setUp()
        self.items = v2_corpus.load_corpus()
        self.eligible = [i for i in self.items if i["eligible_for_verifier"]]
        self.assertEqual(len(self.eligible), 19)

    def _rows(self, mode: str, front_door_rows: int) -> list[dict[str, Any]]:
        rows = []
        left = front_door_rows
        for item in self.items:
            status = item["expected"].get("evidence_status")
            tool = ""
            extra: dict[str, Any] = {}
            if item["eligible_for_verifier"] and left > 0:
                tool = FRONT_DOOR
                extra["verifier_invocation_ok"] = True
                left -= 1
            elif mode == "forced":
                tool = f"jackal_calc.anb:{item['argv'][0]}"
            rows.append(
                record(item["item_id"], mode=mode, invoked_tool=tool,
                       parsed_status=status, **extra)
            )
        return rows

    def _forced(self) -> str:
        return self.receipts.write(self.items, self._rows("forced", 0),
                                   mode="forced")

    def _autonomous(self, front_door_rows: int, **kw) -> str:
        return self.receipts.write(
            self.items, self._rows("autonomous", front_door_rows),
            mode="autonomous",
            transcript=kw.pop("transcript", "/tmp/live-session.json"),
            profile=kw.pop("profile", "full"), **kw,
        )

    def _run(self, *paths: str, extra: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
        argv = [sys.executable, str(GATE_PATH)]
        for path in paths:
            argv += ["--results", path]
        argv += list(extra)
        return subprocess.run(argv, capture_output=True, text=True, cwd=str(ROOT),
                              timeout=180)

    def test_pass_exits_zero_with_the_pass_token(self) -> None:
        proc = self._run(self._forced(), self._autonomous(18))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("EVAL_V2_GATE_PASS exit=0", proc.stdout)
        self.assertNotIn("EVAL_V2_GATE_FAIL", proc.stdout)
        self.assertNotIn("EVAL_V2_GATE_NOT_MEASURABLE", proc.stdout)
        self.assertIn("0.947368 (18/19)", proc.stdout)
        for req in ("req1", "req2", "req3"):
            self.assertIn(f"{req} ", proc.stdout)

    def test_fail_exits_one_with_the_fail_token(self) -> None:
        proc = self._run(self._forced(), self._autonomous(17))
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("EVAL_V2_GATE_FAIL exit=1", proc.stdout)
        self.assertIn("reason=verifier-use-rate-below-threshold", proc.stdout)
        self.assertIn("0.894737 (17/19)", proc.stdout)
        self.assertIn("0.90", proc.stdout)

    def test_no_transcript_exits_three_with_the_not_measurable_token(self) -> None:
        proc = self._run(self._forced(), self._autonomous(0, transcript=None))
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertIn("EVAL_V2_GATE_NOT_MEASURABLE exit=3", proc.stdout)
        self.assertIn("reason=no-transcript-supplied", proc.stdout)
        self.assertNotIn("EVAL_V2_GATE_PASS", proc.stdout)
        self.assertNotIn("EVAL_V2_GATE_FAIL exit=1", proc.stdout)

    def test_forced_only_exits_three_naming_the_by_construction_reason(self) -> None:
        proc = self._run(self._forced())
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertIn("EVAL_V2_GATE_NOT_MEASURABLE exit=3", proc.stdout)
        self.assertIn("reason=forced-mode-verifier-use-by-construction", proc.stdout)
        self.assertIn("by construction", proc.stdout)

    def test_json_summary_carries_the_same_verdict_and_exit_code(self) -> None:
        proc = self._run(self._forced(), self._autonomous(18), extra=("--json",))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        summary = json.loads(proc.stdout)
        self.assertEqual(summary["verdict"], "PASS")
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["authority"], "evals/v2/protocol.md:188-200")
        self.assertEqual(len(summary["findings"]), 3)

    def test_usage_error_exits_two_and_is_not_a_verdict(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(GATE_PATH), "--no-such-flag"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=60,
        )
        self.assertEqual(proc.returncode, 2)
        for token in GATE.VERDICT_TOKEN.values():
            self.assertNotIn(token, proc.stdout)

    def test_cli_has_no_corpus_override(self) -> None:
        """protocol.md lines 198-200: a miss is never reported by re-labelling
        eligibility. A corpus flag on the gate would be that flag."""
        proc = self._run(self._forced(), extra=("--help",))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("--corpus", proc.stdout)
        self.assertNotIn("--eligible", proc.stdout)
        self.assertNotIn("--threshold", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
