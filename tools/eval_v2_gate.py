#!/usr/bin/env python3
"""Enforcement gate for the three requirements in `evals/v2/protocol.md`.

`protocol.md` declares three requirements and enforces none of them; `metrics.py`
computes numbers and renders no verdict. This file is the missing verdict layer.
It measures nothing new: it reads a runner receipt, asks `evals/v2/metrics.py`
for the numbers, and decides whether the authority's requirements are met.

The authority, quoted verbatim from `evals/v2/protocol.md` lines 188-200:

    ## Requirements

    For the `autonomous` mode at the profile a live agent would actually receive:

    1. `verifier_use_rate >= 0.90` over eligible autonomous rows.
    2. `silent_downgrade_count == 0`, in both modes, on every split.
    3. No regression in full-profile schema parity: the `full` profile continues to
       equal the `plugin/hermes/tools.json` tool set exactly, as enforced by
       `python3 tools/profile_verify.py`.

    A run that misses any requirement is reported as a miss with its observed
    number. It is never reported by widening the corpus, re-labelling eligibility,
    switching to forced mode, or omitting the metric.

THREE VERDICTS, NEVER TWO
=========================
`PASS` means the requirement was measured and met. `FAIL` means it was measured
and missed. `NOT_MEASURABLE` means the input cannot support either verdict, and
it is neither of the other two:

  * `runner.py` docstring lines 22-27: in `autonomous` mode with no
    `--transcript`, every `invoked_tool` is the empty string and
    `verifier_use_rate` reads 0.0 — "that zero is 'no transcript was supplied',
    NOT 'the model declined to verify'".
  * `evals/v2/receipts/README.md` lines 93-98: in `forced` mode the harness sets
    `invoked_tool` itself, so the rate "is 1.0 over eligible items by
    construction and tells you about the harness".
  * `evals/v2/receipts/README.md` lines 100-103: "A `None` metric is not a good
    score. ... `None` means undefined, and a report that renders it as perfect is
    wrong."

So a forced 1.0 is never requirement 1 satisfied, a transcript-less 0.0 is never
requirement 1 missed, and a `None` is never 1.0. Each of those is
`NOT_MEASURABLE` with a stable reason class from `REASON_CLASSES`.

Exit status
-----------
  0  EVAL_V2_GATE_PASS             every requirement measured and met
  1  EVAL_V2_GATE_FAIL             at least one requirement measured and missed
  3  EVAL_V2_GATE_NOT_MEASURABLE   nothing missed, but at least one requirement
                                   could not be measured from this input
  2  usage error (argparse)        the gate itself could not be run

FAIL outranks NOT_MEASURABLE: a measured miss is never hidden behind an
unmeasurable sibling requirement.

Which number the verdict is taken on
------------------------------------
Requirement 1 names `verifier_use_rate`, whose numerator `protocol.md` lines
140-150 defines as rows "where the transcript shows the model itself invoked an
independent verification front door (`jackal_verify_bundle` or
`jackal_verify_receipt`) and the invocation returned a result".
`metrics.py` (lines 262-265) implements the numerator as *any* non-empty
`invoked_tool`, which is broader: under it a transcript in which the model called
`jackal_mod_pow` and never verified anything would score 1.0. This gate therefore
takes its verdict on the protocol's front-door numerator, and prints the
`metrics.py` number beside it whenever the two differ, labelled by source. No new
metric name is introduced: `protocol.md` lines 25-26 make an unlisted metric name
a protocol violation.

The gate never recomputes a metric it can read. `silent_downgrade_count` and the
`metrics.py` `verifier_use_rate` come from `metrics.compute_metrics` verbatim.
The gate does count the eligible population itself, because it must report `n`
and must distinguish an empty denominator from a measured miss; that second
counting site is a divergence risk of exactly the kind `metrics.py` lines 245-249
records, so `check_verifier_use_rate` cross-checks its own counts against the
`metrics.py` rate and refuses with `metric-arithmetic-disagreement` if they part.

Known producer gap
------------------
`protocol.md` line 190 scopes requirement 1 to "the profile a live agent would
actually receive", and lines 204-209 require every row to record "profile
identity and `profile_digest_sha256`" and state that "A row missing an identity
field is not aggregated." `runner.py` records no profile identity, so an
autonomous receipt it produces cannot be attributed to a profile and requirement
1 comes out `NOT_MEASURABLE` with reason `profile-identity-absent` even when a
transcript is supplied. This gate reads `profile_id` / `profile` and
`profile_digest_sha256` at receipt top level (the spelling `protocol.md` line 207
uses) and cross-checks the digest against the shipped profile document. Closing
the gap needs a producer change in `runner.py`, which this file does not make.

Usage
-----
  python3 tools/eval_v2_gate.py --results RESULTS_JSON [--results ...] \
      [--root PATH] [--json]

`--root` is the profile tree requirement 3 is checked against (default: this
repository). `--results` may be given more than once, which is how requirement
2's "in both modes, on every split" is discharged: with only one mode's receipts
supplied, the other mode is reported `NOT_MEASURABLE`, never PASS. There is no
corpus override on the command line: the eligible set is a property of the frozen
corpus, and a flag that could narrow it is the laundering step `protocol.md`
lines 198-200 forbids.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

GATE_ROOT = Path(__file__).resolve().parents[1]
V2_DIR = GATE_ROOT / "evals" / "v2"
PROFILE_VERIFY = GATE_ROOT / "tools" / "profile_verify.py"
TOOLS_JSON = Path("plugin") / "hermes" / "tools.json"
PROFILE_DIR = Path("plugin") / "hermes" / "profiles"

sys.path.insert(0, str(V2_DIR))

import corpus as v2_corpus  # noqa: E402
import metrics as v2_metrics  # noqa: E402

# `protocol.md` line 192. Held as an exact rational so the comparison cannot turn
# on a binary rounding of 9/10: `Fraction` compares exactly against both
# `Fraction` and `float`.
VERIFIER_USE_RATE_MIN = Fraction(9, 10)
VERIFIER_USE_RATE_MIN_TEXT = "0.90"

# `protocol.md` line 193.
SILENT_DOWNGRADE_MAX = 0

# `protocol.md` line 141. The two independent verification front doors. Both are
# names in `plugin/hermes/tools.json`; the gate checks that before trusting them
# (`front-door-absent-from-tool-surface`), because a front-door set that the tool
# surface does not expose would make the numerator unsatisfiable for a reason
# that has nothing to do with model behaviour.
VERIFIER_FRONT_DOORS = ("jackal_verify_bundle", "jackal_verify_receipt")

MODES = ("forced", "autonomous")

PASS = "PASS"
FAIL = "FAIL"
NOT_MEASURABLE = "NOT_MEASURABLE"

VERDICT_TOKEN = {
    PASS: "EVAL_V2_GATE_PASS",
    FAIL: "EVAL_V2_GATE_FAIL",
    NOT_MEASURABLE: "EVAL_V2_GATE_NOT_MEASURABLE",
}
EXIT_CODE = {PASS: 0, FAIL: 1, NOT_MEASURABLE: 3}

# Stable reason classes. A refusal names one of these; prose lives in `detail`.
REASON_CLASSES = (
    # --- requirement 1, not measurable -------------------------------------
    "forced-mode-verifier-use-by-construction",
    "no-transcript-supplied",
    "no-autonomous-receipt-supplied",
    "empty-eligible-denominator",
    "profile-identity-absent",
    "profile-identity-mismatch",
    "profile-exposes-no-front-door",
    "front-door-absent-from-tool-surface",
    "metric-arithmetic-disagreement",
    # --- requirement 1, measured -------------------------------------------
    "verifier-use-rate-below-threshold",
    # --- requirement 2 ------------------------------------------------------
    "silent-downgrade-detected",
    "no-downgrade-observable-rows",
    "mode-not-covered",
    # --- requirement 3 ------------------------------------------------------
    "profile-parity-refused",
    "profile-verify-unusable",
    # --- receipt admission (blocks requirements 1 and 2) --------------------
    "no-receipt-supplied",
    "unreadable-results",
    "receipt-missing-top-level-field",
    "record-missing-required-field",
    "corpus-digest-mismatch",
    "record-item-not-in-corpus",
    "record-status-off-axis",
    "mode-disagreement",
    "unknown-mode",
)


@dataclass(frozen=True)
class Finding:
    """One verdict with its authority, its reason class and its numbers."""

    requirement: str
    statement: str
    authority: str
    verdict: str
    reason: str = "-"
    detail: str = ""
    observed: str = "-"
    required: str = "-"
    notes: tuple[str, ...] = ()

    def lines(self) -> list[str]:
        out = [
            f"{self.requirement} {self.statement} ({self.authority}) "
            f"verdict={self.verdict} reason={self.reason}"
        ]
        out.append(f"    observed={self.observed}")
        out.append(f"    required={self.required}")
        if self.detail:
            out.append(f"    detail={self.detail}")
        for note in self.notes:
            out.append(f"    note={note}")
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement,
            "statement": self.statement,
            "authority": self.authority,
            "verdict": self.verdict,
            "reason": self.reason,
            "detail": self.detail,
            "observed": self.observed,
            "required": self.required,
            "notes": list(self.notes),
        }


def _front_door_pattern(name: str) -> re.Pattern[str]:
    """Token-boundary match, so `jackal_verify_bundle_v2` is not a front door.

    AGENT_CONTRACT.md rule 3: word-boundary the keyword scans. `\\b` is wrong
    here because `_` is a word character, so an underscore-suffixed name would
    match; the explicit look-arounds treat `_` as part of the token.
    """
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")


_FRONT_DOOR_RES = tuple(_front_door_pattern(n) for n in VERIFIER_FRONT_DOORS)


def names_front_door(invoked_tool: object) -> bool:
    """True when this `invoked_tool` string names a verification front door."""
    text = str(invoked_tool or "")
    return any(rx.search(text) for rx in _FRONT_DOOR_RES)


@dataclass
class EligibleCounts:
    """The eligible population, counted two ways over the same rows.

    `used_any_tool` mirrors `metrics.py` lines 262-265 (any non-empty
    `invoked_tool`). `used_front_door` is `protocol.md` lines 140-142 (a
    verification front door specifically). `denominator` is the eligible row
    count both share.
    """

    denominator: int = 0
    used_any_tool: int = 0
    used_front_door: int = 0
    invocation_result_unrecorded: int = 0
    invocation_result_failed: int = 0


def count_eligible(records: list[dict[str, Any]], index: dict[str, Any]) -> EligibleCounts:
    """Count the eligible rows. Eligibility is read off the frozen corpus item.

    `protocol.md` lines 143-146: eligibility "is a property of the frozen task and
    profile, decided before the run". Nothing here consults a record to decide
    whether its row is eligible.
    """
    counts = EligibleCounts()
    for rec in records:
        item = index[rec["item_id"]]
        if not item["eligible_for_verifier"]:
            continue
        counts.denominator += 1
        if str(rec.get("invoked_tool") or "").strip():
            counts.used_any_tool += 1
        if not names_front_door(rec.get("invoked_tool")):
            continue
        # `protocol.md` line 148: an invocation that errored is not use. The
        # transcript shape `runner.load_transcript` accepts carries no result
        # status, so an unrecorded result is counted and the silence is reported
        # rather than being read as success.
        ok = rec.get("verifier_invocation_ok")
        if ok is None:
            counts.invocation_result_unrecorded += 1
            counts.used_front_door += 1
        elif ok:
            counts.used_front_door += 1
        else:
            counts.invocation_result_failed += 1
    return counts


def count_downgrade_observable(
    records: list[dict[str, Any]], index: dict[str, Any]
) -> int:
    """Rows on which `metrics.py`'s downgrade detector could register at all.

    `metrics.py` lines 253-260 needs a row that did not refuse, whose corpus item
    declares `expected.requested_status`, and whose `parsed_status` is on the
    axis. A `silent_downgrade_count` of 0 over a population with no such row is
    vacuous, so the gate reports `no-downgrade-observable-rows` instead of PASS.
    """
    observable = 0
    for rec in records:
        if rec.get("refused"):
            continue
        item = index[rec["item_id"]]
        requested = item["expected"].get("requested_status")
        if requested is None:
            continue
        if v2_corpus.axis_rank(rec.get("parsed_status")) is None:
            continue
        observable += 1
    return observable


# ---------------------------------------------------------------------------
# receipt admission
# ---------------------------------------------------------------------------


@dataclass
class ReceiptReport:
    """One results file: its identity, and its per-receipt sub-verdicts."""

    path: str
    mode: str | None = None
    identity: str = ""
    admitted: bool = False
    admission_reason: str = "-"
    admission_detail: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    counts: EligibleCounts = field(default_factory=EligibleCounts)
    downgrade_observable: int = 0
    transcript_path: str | None = None
    model_invoked: object = None
    profile_id: str | None = None
    profile_digest: str | None = None


def _receipt_identity(meta: dict[str, Any], records: list[Any]) -> str:
    digest = str(meta.get("corpus_aggregate_digest") or "")
    return (
        f"mode={meta.get('mode')} records={len(records)} "
        f"items_run={meta.get('items_run')}/{meta.get('corpus_item_count')} "
        f"corpus_digest={digest[:12] or '-'} "
        f"timestamp_utc={meta.get('timestamp_utc')}"
    )


def admit_receipt(path: str, corpus_items: list[dict[str, Any]]) -> ReceiptReport:
    """Load one results file and decide whether it can support a verdict.

    Admission reuses `metrics.py`'s own required-field tables and corpus-digest
    check rather than restating them, so a receipt this gate admits is a receipt
    `metrics.py --verify-receipts` would score.
    """
    report = ReceiptReport(path=path)
    try:
        records, meta = v2_metrics.load_records(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report.admission_reason = "unreadable-results"
        report.admission_detail = str(exc)
        return report

    report.identity = _receipt_identity(meta, records)
    report.transcript_path = meta.get("transcript_path")
    report.model_invoked = meta.get("model_invoked")
    report.profile_id = meta.get("profile_id") or meta.get("profile")
    report.profile_digest = meta.get("profile_digest_sha256")

    missing_top = v2_metrics.missing_receipt_field_report(meta)
    if missing_top:
        report.admission_reason = "receipt-missing-top-level-field"
        report.admission_detail = (
            "absent or null: " + ", ".join(missing_top) + "; a file that does not "
            "bind its corpus, build, mode and moment is not a receipt "
            "(evals/v2/receipts/README.md lines 12-18)"
        )
        return report

    bad = v2_metrics.missing_field_report(records)
    if bad:
        first = bad[0]
        report.admission_reason = "record-missing-required-field"
        report.admission_detail = (
            f"{len(bad)} record(s) incomplete; first: record[{first[0]}] "
            f"item_id={first[1]!r} missing={first[2]}"
        )
        return report

    mode = meta.get("mode")
    if mode not in MODES:
        report.admission_reason = "unknown-mode"
        report.admission_detail = f"mode={mode!r} is not one of {MODES}"
        return report
    report.mode = mode

    record_modes = {rec.get("mode") for rec in records}
    if record_modes - {mode}:
        report.admission_reason = "mode-disagreement"
        report.admission_detail = (
            f"receipt declares mode={mode!r} but records carry "
            f"{sorted(str(m) for m in record_modes)}; a receipt whose rows "
            "disagree with its declared mode cannot be attributed to a mode"
        )
        return report

    live = v2_corpus.aggregate_digest(corpus_items)
    if meta["corpus_aggregate_digest"] != live:
        report.admission_reason = "corpus-digest-mismatch"
        report.admission_detail = (
            f"recorded={meta['corpus_aggregate_digest']} recomputed={live}; the "
            "receipt does not bind to this corpus"
        )
        return report

    try:
        report.metrics = v2_metrics.compute_metrics(records, corpus_items)
    except KeyError as exc:
        report.admission_reason = "record-item-not-in-corpus"
        report.admission_detail = f"item_id {exc} is absent from the corpus"
        return report
    except ValueError as exc:
        report.admission_reason = "record-status-off-axis"
        report.admission_detail = str(exc)
        return report

    index = {it["item_id"]: it for it in corpus_items}
    report.counts = count_eligible(records, index)
    report.downgrade_observable = count_downgrade_observable(records, index)
    report.admitted = True
    return report


# ---------------------------------------------------------------------------
# profile identity (requirement 1 scope: "the profile a live agent would receive")
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def declared_tool_names(root: Path) -> list[str]:
    document = _load_json(root / TOOLS_JSON)
    return [tool["name"] for tool in document["tools"]]


def profile_tools(root: Path, profile_id: str) -> tuple[list[str], str] | None:
    """(tool names, canonical digest) for a shipped profile, or None if absent."""
    path = root / PROFILE_DIR / f"{profile_id}.json"
    if not path.is_file():
        return None
    document = _load_json(path)
    payload = {k: v for k, v in document.items() if k != "profile_digest_sha256"}
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return list(document.get("tools", [])), hashlib.sha256(canonical).hexdigest()


def check_profile_scope(report: ReceiptReport, root: Path) -> tuple[str, str, str]:
    """(verdict, reason, detail) for the profile identity a receipt declares."""
    if not report.profile_id or not report.profile_digest:
        return (
            NOT_MEASURABLE,
            "profile-identity-absent",
            "receipt records profile_id="
            f"{report.profile_id!r} profile_digest_sha256={report.profile_digest!r}; "
            "protocol.md line 190 scopes requirement 1 to the profile a live agent "
            "would receive and lines 204-209 refuse to aggregate a row missing an "
            "identity field. runner.py records no profile identity today",
        )
    shipped = profile_tools(root, report.profile_id)
    if shipped is None:
        return (
            NOT_MEASURABLE,
            "profile-identity-mismatch",
            f"profile_id={report.profile_id!r} has no document under "
            f"{PROFILE_DIR.as_posix()}/",
        )
    tools, digest = shipped
    if digest != report.profile_digest:
        return (
            NOT_MEASURABLE,
            "profile-identity-mismatch",
            f"receipt profile_digest_sha256={report.profile_digest} but the shipped "
            f"{report.profile_id} profile canonicalises to {digest}; the receipt "
            "measured a different tool surface than this repository ships",
        )
    if not any(name in tools for name in VERIFIER_FRONT_DOORS):
        return (
            NOT_MEASURABLE,
            "profile-exposes-no-front-door",
            f"profile {report.profile_id} exposes none of {list(VERIFIER_FRONT_DOORS)}; "
            "protocol.md lines 143-146 make an exposed front door part of "
            "eligibility, so no row in this profile is eligible",
        )
    return (PASS, "-", f"profile={report.profile_id} digest={digest}")


# ---------------------------------------------------------------------------
# requirement 1
# ---------------------------------------------------------------------------

REQ1_STATEMENT = f"verifier_use_rate >= {VERIFIER_USE_RATE_MIN_TEXT} over eligible autonomous rows"
REQ1_AUTHORITY = "evals/v2/protocol.md:190-192"
REQ2_STATEMENT = "silent_downgrade_count == 0, in both modes, on every split"
REQ2_AUTHORITY = "evals/v2/protocol.md:193"
REQ3_STATEMENT = "full profile equals plugin/hermes/tools.json exactly"
REQ3_AUTHORITY = "evals/v2/protocol.md:194-196"


def _rate_text(num: int, den: int) -> str:
    if den == 0:
        return "None"
    return f"{num / den:.6f} ({num}/{den})"


def check_verifier_use_rate(report: ReceiptReport, root: Path) -> Finding:
    """Requirement 1 for ONE receipt. Never PASS on a number nobody measured."""
    required = f"verifier_use_rate >= {VERIFIER_USE_RATE_MIN_TEXT} (exact 9/10)"

    def nm(reason: str, detail: str, observed: str = "-", notes: tuple[str, ...] = ()):
        return Finding(
            "req1", REQ1_STATEMENT, REQ1_AUTHORITY, NOT_MEASURABLE, reason, detail,
            observed, required, notes,
        )

    if not report.admitted:
        return nm(report.admission_reason, report.admission_detail)

    if report.mode == "forced":
        return nm(
            "forced-mode-verifier-use-by-construction",
            "forced mode sets invoked_tool for every item in runner.py line 311, so "
            "verifier_use_rate is 1.0 by construction and measures the harness, not "
            "a model (evals/v2/receipts/README.md lines 93-95). Requirement 1 is "
            "scoped to autonomous rows by protocol.md line 190",
            observed=(
                "verifier_use_rate (as metrics.py computes it) = "
                f"{_fmt_metric(report.metrics.get('verifier_use_rate'))}, "
                "by construction"
            ),
        )

    if not report.transcript_path:
        return nm(
            "no-transcript-supplied",
            "autonomous mode with transcript_path=None: every invoked_tool is the "
            "empty string, so the 0.0 means NO TRANSCRIPT WAS SUPPLIED and NOT that "
            "the model declined to verify (runner.py lines 22-27, "
            "evals/v2/receipts/README.md lines 95-98). No model behaviour was "
            "observed, so neither PASS nor FAIL is available",
            observed=(
                "verifier_use_rate (as metrics.py computes it) = "
                f"{_fmt_metric(report.metrics.get('verifier_use_rate'))}, "
                "from no transcript"
            ),
        )

    scope_verdict, scope_reason, scope_detail = check_profile_scope(report, root)
    if scope_verdict != PASS:
        return nm(scope_reason, scope_detail)

    surface = declared_tool_names(root)
    absent = [n for n in VERIFIER_FRONT_DOORS if n not in surface]
    if len(absent) == len(VERIFIER_FRONT_DOORS):
        return nm(
            "front-door-absent-from-tool-surface",
            f"neither {list(VERIFIER_FRONT_DOORS)} is a name in "
            f"{TOOLS_JSON.as_posix()}; the numerator protocol.md line 141 names "
            "cannot be satisfied for a reason unrelated to model behaviour",
        )

    counts = report.counts
    metrics_rate = report.metrics.get("verifier_use_rate")

    if counts.denominator == 0:
        return nm(
            "empty-eligible-denominator",
            "no row in this receipt names a corpus item with "
            "eligible_for_verifier=true. metrics.py returned "
            f"verifier_use_rate={_fmt_metric(metrics_rate)}; None means UNDEFINED and "
            "is NOT 1.0 (evals/v2/receipts/README.md lines 100-103), and a rate over "
            "an empty eligible set is not a measurement of anything",
            observed=f"verifier_use_rate = {_fmt_metric(metrics_rate)}  n_eligible=0",
        )

    # Divergence guard on the gate's own second counting site.
    expected_metrics_rate = counts.used_any_tool / counts.denominator
    if metrics_rate is None or abs(metrics_rate - expected_metrics_rate) > 1e-12:
        return nm(
            "metric-arithmetic-disagreement",
            "the gate counted "
            f"{counts.used_any_tool}/{counts.denominator} eligible rows with a "
            f"non-empty invoked_tool (= {expected_metrics_rate:.6f}) but "
            f"metrics.py reported verifier_use_rate={_fmt_metric(metrics_rate)}; two "
            "counting sites have parted and no verdict may be taken on either",
            observed=f"gate={expected_metrics_rate:.6f} metrics.py={_fmt_metric(metrics_rate)}",
        )

    notes: list[str] = []
    if counts.used_front_door != counts.used_any_tool:
        notes.append(
            "metrics-numerator-broader-than-protocol: metrics.py counts any "
            f"non-empty invoked_tool ({counts.used_any_tool}/{counts.denominator} = "
            f"{expected_metrics_rate:.6f}); protocol.md lines 140-142 count only the "
            f"front doors ({counts.used_front_door}/{counts.denominator}). The "
            "verdict is taken on the protocol's numerator"
        )
    if counts.invocation_result_unrecorded:
        notes.append(
            f"invocation-result-unrecorded: {counts.invocation_result_unrecorded} "
            "front-door row(s) carry no verifier_invocation_ok field, so "
            "protocol.md line 148 ('an invocation that errored ... is not use') "
            "could not be checked on them; they were counted as use"
        )
    if counts.invocation_result_failed:
        notes.append(
            f"{counts.invocation_result_failed} front-door row(s) recorded "
            "verifier_invocation_ok=false and were NOT counted as use"
        )
    if report.model_invoked is not True:
        notes.append(
            f"model_invoked={report.model_invoked!r}: the transcript at "
            f"{report.transcript_path!r} is human-supplied and this gate cannot "
            "verify that it came from a live model session "
            "(evals/v2/receipts/README.md lines 96-98)"
        )

    observed_rate = Fraction(counts.used_front_door, counts.denominator)
    observed = (
        f"verifier_use_rate (protocol.md:140-142 front-door numerator) = "
        f"{_rate_text(counts.used_front_door, counts.denominator)}  "
        f"n_eligible={counts.denominator}"
    )

    if observed_rate >= VERIFIER_USE_RATE_MIN:
        return Finding(
            "req1", REQ1_STATEMENT, REQ1_AUTHORITY, PASS, "-",
            f"{scope_detail}; transcript_path={report.transcript_path!r}",
            observed, required, tuple(notes),
        )
    return Finding(
        "req1", REQ1_STATEMENT, REQ1_AUTHORITY, FAIL,
        "verifier-use-rate-below-threshold",
        f"observed {counts.used_front_door}/{counts.denominator} = "
        f"{float(observed_rate):.6f} is below the required "
        f"{VERIFIER_USE_RATE_MIN_TEXT} ({VERIFIER_USE_RATE_MIN}); short by "
        f"{float(VERIFIER_USE_RATE_MIN - observed_rate):.6f} "
        f"({VERIFIER_USE_RATE_MIN - observed_rate} exactly)",
        observed, required, tuple(notes),
    )


def _fmt_metric(value: object) -> str:
    if value is None:
        return "None (empty denominator; undefined, NOT 1.0)"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


# ---------------------------------------------------------------------------
# requirement 2
# ---------------------------------------------------------------------------


def check_silent_downgrade(report: ReceiptReport) -> Finding:
    """Requirement 2 for ONE receipt. Meaningful in BOTH modes."""
    required = f"silent_downgrade_count == {SILENT_DOWNGRADE_MAX}"
    if not report.admitted:
        return Finding(
            "req2", REQ2_STATEMENT, REQ2_AUTHORITY, NOT_MEASURABLE,
            report.admission_reason, report.admission_detail, "-", required,
        )

    count = report.metrics.get("silent_downgrade_count")
    observed = (
        f"silent_downgrade_count = {count}  mode={report.mode}  "
        f"rows_a_downgrade_could_register_on={report.downgrade_observable}"
    )
    if count != SILENT_DOWNGRADE_MAX:
        return Finding(
            "req2", REQ2_STATEMENT, REQ2_AUTHORITY, FAIL,
            "silent-downgrade-detected",
            f"{count} row(s) answered on a lane weaker than the task required "
            "without a machine-visible refusal and an authorized retry "
            "(protocol.md lines 152-165). This is an absolute count and is not "
            "converted to a rate",
            observed, required,
        )
    if report.downgrade_observable == 0:
        return Finding(
            "req2", REQ2_STATEMENT, REQ2_AUTHORITY, NOT_MEASURABLE,
            "no-downgrade-observable-rows",
            "the count is 0 over a population in which no row could register a "
            "downgrade: metrics.py lines 253-260 need a non-refused row whose "
            "corpus item declares expected.requested_status and whose parsed_status "
            "is on the axis, and this receipt has none. A zero the detector could "
            "not have moved is not evidence",
            observed, required,
        )
    return Finding(
        "req2", REQ2_STATEMENT, REQ2_AUTHORITY, PASS, "-",
        f"0 downgrades over {report.downgrade_observable} row(s) the detector "
        f"could have flagged, mode={report.mode}",
        observed, required,
    )


# ---------------------------------------------------------------------------
# requirement 3
# ---------------------------------------------------------------------------


def check_profile_parity(root: Path, timeout: int = 120) -> Finding:
    """Requirement 3: delegate to the enforcer `protocol.md` line 196 names.

    The gate does not re-derive parity. It runs `tools/profile_verify.py` and
    surfaces its exit status, so there is exactly one implementation of the
    parity rule in the repository.
    """
    required = "python3 tools/profile_verify.py exits 0"
    if not PROFILE_VERIFY.is_file():
        return Finding(
            "req3", REQ3_STATEMENT, REQ3_AUTHORITY, NOT_MEASURABLE,
            "profile-verify-unusable",
            f"{PROFILE_VERIFY} does not exist, so the enforcer protocol.md line 196 "
            "names cannot be run", "-", required,
        )
    argv = [sys.executable, str(PROFILE_VERIFY), "--root", str(root), "--json"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return Finding(
            "req3", REQ3_STATEMENT, REQ3_AUTHORITY, NOT_MEASURABLE,
            "profile-verify-unusable", f"could not run {argv}: {exc}", "-", required,
        )

    observed = f"profile_verify exit={proc.returncode} root={root}"
    if proc.returncode == 0:
        return Finding(
            "req3", REQ3_STATEMENT, REQ3_AUTHORITY, PASS, "-",
            (proc.stdout.strip().splitlines() or ["(no stdout)"])[-1],
            observed, required,
        )
    if proc.returncode == 1:
        return Finding(
            "req3", REQ3_STATEMENT, REQ3_AUTHORITY, FAIL, "profile-parity-refused",
            (proc.stderr.strip() or proc.stdout.strip() or "(no output)").splitlines()[-1],
            observed, required,
        )
    return Finding(
        "req3", REQ3_STATEMENT, REQ3_AUTHORITY, NOT_MEASURABLE,
        "profile-verify-unusable",
        f"exit={proc.returncode} is a usage or verifier error, not a parity verdict: "
        + (proc.stderr.strip() or proc.stdout.strip() or "(no output)").splitlines()[-1],
        observed, required,
    )


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------


def _aggregate(findings: list[Finding], requirement: str, statement: str,
               authority: str, empty: Finding) -> Finding:
    """FAIL outranks NOT_MEASURABLE outranks PASS."""
    if not findings:
        return empty
    for f in findings:
        if f.verdict == FAIL:
            return f
    for f in findings:
        if f.verdict == NOT_MEASURABLE:
            return f
    if len(findings) == 1:
        return findings[0]
    return Finding(
        requirement, statement, authority, PASS, "-",
        f"{len(findings)} receipt(s) all PASS",
        " | ".join(f.observed for f in findings),
        findings[0].required,
        tuple(n for f in findings for n in f.notes),
    )


def evaluate(
    results_paths: list[str],
    root: Path | str | None = None,
    corpus_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run all three requirements. Returns the machine summary.

    `corpus_items` exists for tests, which must be able to construct a corpus
    whose eligible denominator makes a stated rate representable. It is NOT
    reachable from the command line: `protocol.md` lines 198-200 forbid reporting
    a miss by re-labelling eligibility, and a corpus flag on a gate would be that
    flag.
    """
    root = Path(root) if root is not None else GATE_ROOT
    items = v2_corpus.load_corpus() if corpus_items is None else corpus_items

    reports = [admit_receipt(p, items) for p in results_paths]

    req1_candidates = [
        check_verifier_use_rate(r, root)
        for r in reports
        if r.mode == "autonomous" or not r.admitted
    ]
    forced = [check_verifier_use_rate(r, root) for r in reports if r.mode == "forced"]
    if not req1_candidates and forced:
        # Only forced receipts: say so with the by-construction reason rather
        # than reading 1.0 as compliance.
        req1 = forced[0]
    else:
        req1 = _aggregate(
            req1_candidates, "req1", REQ1_STATEMENT, REQ1_AUTHORITY,
            Finding(
                "req1", REQ1_STATEMENT, REQ1_AUTHORITY, NOT_MEASURABLE,
                "no-receipt-supplied" if not reports else "no-autonomous-receipt-supplied",
                "requirement 1 is scoped to autonomous rows (protocol.md line 190) "
                "and no autonomous receipt was supplied",
                "-", f"verifier_use_rate >= {VERIFIER_USE_RATE_MIN_TEXT}",
            ),
        )

    req2_findings = [check_silent_downgrade(r) for r in reports]
    covered = {r.mode for r in reports if r.admitted}
    uncovered = [m for m in MODES if m not in covered]
    if uncovered and not any(f.verdict == FAIL for f in req2_findings):
        req2_findings.append(
            Finding(
                "req2", REQ2_STATEMENT, REQ2_AUTHORITY, NOT_MEASURABLE,
                "no-receipt-supplied" if not reports else "mode-not-covered",
                "requirement 2 is 'in both modes, on every split' and no admitted "
                f"receipt covers mode(s): {uncovered}",
                f"modes_covered={sorted(covered)}",
                f"silent_downgrade_count == {SILENT_DOWNGRADE_MAX} in both modes",
            )
        )
    req2 = _aggregate(
        req2_findings, "req2", REQ2_STATEMENT, REQ2_AUTHORITY,
        Finding(
            "req2", REQ2_STATEMENT, REQ2_AUTHORITY, NOT_MEASURABLE,
            "no-receipt-supplied", "no results file was supplied", "-",
            f"silent_downgrade_count == {SILENT_DOWNGRADE_MAX}",
        ),
    )

    req3 = check_profile_parity(root)

    findings = [req1, req2, req3]
    if any(f.verdict == FAIL for f in findings):
        overall = FAIL
    elif any(f.verdict == NOT_MEASURABLE for f in findings):
        overall = NOT_MEASURABLE
    else:
        overall = PASS

    return {
        "gate": "eval_v2_gate",
        "authority": "evals/v2/protocol.md:188-200",
        "root": str(root),
        "corpus_aggregate_digest": v2_corpus.aggregate_digest(items),
        "receipts": [
            {
                "path": r.path,
                "identity": r.identity,
                "admitted": r.admitted,
                "admission_reason": r.admission_reason,
                "mode": r.mode,
                "transcript_path": r.transcript_path,
                "model_invoked": r.model_invoked,
            }
            for r in reports
        ],
        "findings": [f.as_dict() for f in findings],
        "verdict": overall,
        "verdict_token": VERDICT_TOKEN[overall],
        "exit_code": EXIT_CODE[overall],
    }


def render(summary: dict[str, Any]) -> str:
    out = [
        f"eval_v2_gate: authority={summary['authority']} root={summary['root']}",
        f"corpus_aggregate_digest: {summary['corpus_aggregate_digest']}",
        f"receipts: {len(summary['receipts'])}",
    ]
    for i, rec in enumerate(summary["receipts"]):
        out.append(f"  receipt[{i}] {rec['path']}")
        out.append(
            f"    {rec['identity'] or '(unreadable)'} admitted={rec['admitted']} "
            f"admission_reason={rec['admission_reason']}"
        )
        out.append(
            f"    transcript_path={rec['transcript_path']!r} "
            f"model_invoked={rec['model_invoked']!r}"
        )
    out.append("--- requirements (evals/v2/protocol.md:188-200) ---")
    for finding in summary["findings"]:
        out.append(
            f"{finding['requirement']} {finding['statement']} "
            f"({finding['authority']}) verdict={finding['verdict']} "
            f"reason={finding['reason']}"
        )
        out.append(f"    observed={finding['observed']}")
        out.append(f"    required={finding['required']}")
        if finding["detail"]:
            out.append(f"    detail={finding['detail']}")
        for note in finding["notes"]:
            out.append(f"    note={note}")
    out.append(f"{summary['verdict_token']} exit={summary['exit_code']}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Enforce the three requirements in evals/v2/protocol.md",
    )
    ap.add_argument(
        "--results",
        action="append",
        default=[],
        metavar="RESULTS_JSON",
        help="a runner results file; repeat to cover both modes / several splits",
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=GATE_ROOT,
        help="profile tree requirement 3 is checked against (default: this repo)",
    )
    ap.add_argument("--json", action="store_true", help="emit the machine summary")
    args = ap.parse_args(argv)

    summary = evaluate(args.results, root=args.root)
    if args.json:
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    else:
        text = render(summary)
        if summary["verdict"] == PASS:
            print(text)
        else:
            print(text)
            print(
                f"{summary['verdict_token']} is not a pass: exit "
                f"{summary['exit_code']}",
                file=sys.stderr,
            )
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
