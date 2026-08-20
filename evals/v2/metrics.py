#!/usr/bin/env python3
"""JACKAL eval v2 metrics — exactly eight names, each with one stated definition.

The eight names, and nothing else, are in `METRIC_NAMES`:

  accuracy                 passed / total, over items whose category is NOT
                           `refusal_expected`. Refusal items are scored by the
                           refusal metrics; folding them into accuracy would let
                           a build that refuses everything score well.

  false_strong_claim_rate  Fraction of records that over-claim on EITHER
                           registry axis. Denominator: all records.
                           Mathematical axis: `parsed_status` sits STRICTLY
                           higher than the item's `expected.evidence_status`.
                           Ranks come from the registry's own
                           `axis_orders.mathematical_ranks`, in which `estimated`
                           and `model-based` are EQUAL, so answering an
                           `estimated`-evidence item with `model-based` is not an
                           over-claim and must not be counted as one.
                           Consequence axis: the `consequence=` class the engine
                           printed sits STRICTLY higher than the item's
                           `expected.consequence_ceiling`. The two axes are
                           independent — a `structural-exact` fact is genuinely
                           `exact` on the mathematical axis and still capped at
                           `informational` on the consequence axis — and a record
                           that over-claims on either is one over-claim, counted
                           once. A record with no status token and no consequence
                           token asserts nothing and therefore cannot over-claim;
                           it is counted in the denominator and never in the
                           numerator.

  refusal_precision        correctly-refused / all-refused. A record is
                           all-refused if `refused` is true. It is
                           correctly-refused if it is also a `refusal_expected`
                           item that passed (i.e. the named reason matched).
                           EMPTY DENOMINATOR RETURNS None, NOT 1.0. A build that
                           never refuses has undefined refusal precision; a
                           vacuous 1.0 would read as perfect fail-closed
                           behaviour and is a dishonest metric.

  refusal_recall           correctly-refused / all `refusal_expected` items.
                           Empty denominator returns None.

  verifier_use_rate        records with a non-empty `invoked_tool` / records
                           whose corpus item has `eligible_for_verifier` true.
                           Empty denominator returns None.

  silent_downgrade_count   COUNT (not a rate) of records where the invocation
                           requested a stronger lane than the status returned,
                           and the engine did NOT refuse. Requires both a
                           `requested_status` and a `parsed_status`: an absent
                           status token is no claim rather than a weak one, so it
                           is not read as a downgrade.

  latency_ms_p50           Nearest-rank percentile over `latency_ms`:
  latency_ms_p95           index = ceil(p/100 * n) - 1 on the ascending sort,
                           clamped to [0, n-1]. No interpolation, so the value is
                           always an observed measurement. None when n == 0.

This module only reads records and recomputes arithmetic. It never chooses a
different operation, substitutes an answer, or raises an assurance class
(AGENT_CONTRACT.md rule 4).
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus import (  # noqa: E402
    aggregate_digest,
    axis_rank,
    consequence_rank,
    load_corpus,
)

METRIC_NAMES = (
    "accuracy",
    "false_strong_claim_rate",
    "refusal_precision",
    "refusal_recall",
    "verifier_use_rate",
    "silent_downgrade_count",
    "latency_ms_p50",
    "latency_ms_p95",
)

REQUIRED_RECORD_FIELDS = (
    "item_id",
    "mode",
    "invoked_tool",
    "raw_stdout",
    "parsed_status",
    "passed",
    "refused",
    "latency_ms",
)

# Top-level receipt fields. `evals/v2/receipts/README.md` states that a receipt
# binds the corpus it was scored against, the engine identity, the mode and the
# timestamp; every one of those lives at the top level of the results object, not
# on a record. A receipt missing any of them binds LESS than the README promises,
# so `--verify-receipts` refuses it by name rather than scoring it. A bare list of
# records has no top level at all and is refused for all four reasons at once.
REQUIRED_RECEIPT_FIELDS = (
    "corpus_aggregate_digest",
    "engine_identity",
    "mode",
    "timestamp_utc",
)

# The engine prints its consequence class on its own line, e.g.
# `consequence=informational note=...`. Scored from the record's `raw_stdout`
# bytes rather than from any summary field, so a receipt cannot dodge the
# consequence check by omitting a key. `raw_stdout` is a required record field.
CONSEQUENCE_RE = re.compile(r"^consequence[= ]([a-z][a-z-]*)", re.MULTILINE)


def parse_consequence(stdout):
    """Consequence class asserted in these bytes, or None if none is asserted."""
    m = CONSEQUENCE_RE.search(stdout or "")
    return m.group(1) if m else None


def missing_receipt_field_report(meta):
    """Return the REQUIRED_RECEIPT_FIELDS absent or null in a results object."""
    return [f for f in REQUIRED_RECEIPT_FIELDS if meta.get(f) is None]


def missing_field_report(records):
    """Return [(index, item_id_or_None, [missing field names])] for bad records."""
    bad = []
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            bad.append((i, None, list(REQUIRED_RECORD_FIELDS)))
            continue
        miss = [f for f in REQUIRED_RECORD_FIELDS if f not in rec]
        if miss:
            bad.append((i, rec.get("item_id"), miss))
    return bad


# The axis tables and the `structural-exact` alias live in corpus.py, which owns
# the registry vocabulary. This module compares ranks and nothing else: it never
# invents a rank for a token it does not recognise, because defaulting an unknown
# engine status to some rank would score a claim whose assurance nobody has
# established (AGENT_CONTRACT.md rule 4).
_rank = axis_rank


def _nearest_rank(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    idx = math.ceil(pct / 100.0 * len(ordered)) - 1
    idx = max(0, min(len(ordered) - 1, idx))
    return ordered[idx]


def _ratio(num, den):
    """None on an empty denominator. Never 1.0-by-vacuity."""
    if den == 0:
        return None
    return num / den


def compute_metrics(records, corpus=None):
    """Recompute all eight metrics. `corpus` defaults to the v2 corpus.

    Raises KeyError if a record names an item_id absent from the corpus: such a
    receipt does not bind to this corpus and must not be scored against it.

    Raises ValueError if a record asserts a status token that is not a registry
    axis point or a declared alias of one, or a consequence class that is not a
    registry consequence class. Both are refusals, not defaults: a token nobody
    has placed on an axis cannot be compared against one.
    """
    items = load_corpus() if corpus is None else corpus
    index = {it["item_id"]: it for it in items}

    acc_num = acc_den = 0
    refused_total = 0
    correct_refusals = 0
    expected_refusals = 0
    strong_num = 0
    strong_den = 0
    downgrades = 0
    ver_num = ver_den = 0
    latencies = []

    for rec in records:
        item = index[rec["item_id"]]
        exp = item["expected"]
        category = item["category"]

        if category != "refusal_expected":
            acc_den += 1
            if rec["passed"]:
                acc_num += 1
        else:
            expected_refusals += 1

        if rec["refused"]:
            refused_total += 1
            if category == "refusal_expected" and rec["passed"]:
                correct_refusals += 1

        # --- axis 1: mathematical assurance ---------------------------------
        # STRICT `>`. The registry gives `estimated` and `model-based` the SAME
        # rank, so a `model-based` answer to an `estimated`-evidence item is a
        # lateral move, not an over-claim, and a `>=` here would manufacture a
        # false_strong_claim finding out of correct engine behaviour.
        parsed_rank = _rank(rec["parsed_status"])
        evidence_rank = _rank(exp.get("evidence_status"))
        over_math = parsed_rank is not None and (
            evidence_rank is None or parsed_rank > evidence_rank
        )

        # --- axis 2: consequence class --------------------------------------
        # Read from the record's own stdout bytes, not from a summary field. A
        # `structural-exact` fact is `exact` on axis 1 and still capped at
        # `informational` here; ignoring this axis would let "this test exists"
        # be scored as though it were safety-critical evidence, which is the
        # laundering step this whole harness exists to detect. A record that
        # prints no `consequence=` token asserts no consequence class and cannot
        # over-claim on this axis, exactly as an absent status token cannot
        # over-claim on axis 1.
        emitted_consequence = consequence_rank(parse_consequence(rec["raw_stdout"]))
        ceiling = consequence_rank(exp.get("consequence_ceiling"))
        over_consequence = emitted_consequence is not None and (
            ceiling is None or emitted_consequence > ceiling
        )

        # One record, one over-claim, whichever axis it came from.
        if over_math or over_consequence:
            strong_num += 1

        # Denominator: records that actually asserted something. A refused row
        # emits no claim, so it cannot emit a false one, and counting it would
        # dilute the rate by however many refusals the corpus happens to carry.
        # `evals/v2/protocol.md` states this ("Refused rows are excluded from the
        # denominator because they emit no claim"); an earlier revision of this
        # file used `len(records)` instead, so the same receipt yielded 0/50 here
        # and 0/42 under the protocol. Both read 0.0 while the numerator was zero,
        # which is exactly how a divergence like this survives unnoticed.
        if not rec["refused"]:
            strong_den += 1

        requested_rank = _rank(exp.get("requested_status"))
        if (
            not rec["refused"]
            and requested_rank is not None
            and parsed_rank is not None
            and parsed_rank < requested_rank
        ):
            downgrades += 1

        if item["eligible_for_verifier"]:
            ver_den += 1
            if str(rec["invoked_tool"] or "").strip():
                ver_num += 1

        latencies.append(rec["latency_ms"])

    return {
        "accuracy": _ratio(acc_num, acc_den),
        "false_strong_claim_rate": _ratio(strong_num, strong_den),
        "refusal_precision": _ratio(correct_refusals, refused_total),
        "refusal_recall": _ratio(correct_refusals, expected_refusals),
        "verifier_use_rate": _ratio(ver_num, ver_den),
        "silent_downgrade_count": downgrades,
        "latency_ms_p50": _nearest_rank(latencies, 50),
        "latency_ms_p95": _nearest_rank(latencies, 95),
    }


def load_records(path):
    """Return (records, meta) from a results file.

    A bare list of records is accepted at this layer and comes back with an EMPTY
    meta, which `--verify-receipts` then refuses: a list of records is not a
    receipt, because it binds no corpus digest, no engine identity, no mode and no
    timestamp. Parsing and binding are kept separate on purpose so a caller that
    genuinely wants to score loose records (the unit tests do) can, while the CLI
    that prints a verification verdict cannot.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload, {}
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        meta = {k: v for k, v in payload.items() if k != "records"}
        return payload["records"], meta
    raise ValueError(
        f"{path}: expected a list of records or an object with a 'records' list"
    )


def _fmt(name, value):
    if value is None:
        return f"{name} = None    (empty denominator; undefined, NOT 1.0)"
    if name == "silent_downgrade_count":
        return f"{name} = {value}"
    if name.startswith("latency_ms"):
        return f"{name} = {value:.3f}"
    return f"{name} = {value:.6f}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="JACKAL eval v2 metrics")
    ap.add_argument(
        "--verify-receipts",
        metavar="RESULTS_JSON",
        required=True,
        help="recompute all eight metrics from a runner results file",
    )
    args = ap.parse_args(argv)

    try:
        records, meta = load_records(args.verify_receipts)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"RECEIPT_VERIFY_FAIL unreadable: {exc}", file=sys.stderr)
        return 2

    print(f"receipts: {args.verify_receipts}")
    print(f"records: {len(records)}")

    bad = missing_field_report(records)
    if bad:
        print(
            f"RECEIPT_VERIFY_FAIL {len(bad)} record(s) missing required field(s):",
            file=sys.stderr,
        )
        for idx, item_id, miss in bad:
            print(f"  record[{idx}] item_id={item_id!r} missing={miss}", file=sys.stderr)
        print(
            "required fields: " + ", ".join(REQUIRED_RECORD_FIELDS),
            file=sys.stderr,
        )
        return 1

    missing_top = missing_receipt_field_report(meta)
    if missing_top:
        print(
            "RECEIPT_VERIFY_FAIL missing required top-level receipt field(s): "
            + ", ".join(missing_top),
            file=sys.stderr,
        )
        print(
            "a receipt binds the corpus digest, the engine identity, the mode and "
            "the timestamp (evals/v2/receipts/README.md); one that omits any of "
            "them binds less than the README promises and is not scored",
            file=sys.stderr,
        )
        print(
            "required top-level fields: " + ", ".join(REQUIRED_RECEIPT_FIELDS),
            file=sys.stderr,
        )
        return 1

    items = load_corpus()
    live_aggregate = aggregate_digest(items)
    recorded = meta["corpus_aggregate_digest"]
    match = recorded == live_aggregate
    print(f"corpus_aggregate_digest (recorded): {recorded}")
    print(f"corpus_aggregate_digest (recomputed): {live_aggregate}")
    print(f"corpus_digest_match: {match}")
    if not match:
        print(
            "RECEIPT_VERIFY_FAIL receipt does not bind to this corpus",
            file=sys.stderr,
        )
        return 1

    # Present by now: every one of these was required above.
    for key in ("engine_identity", "mode", "timestamp_utc"):
        print(f"{key}: {meta[key]}")

    try:
        metrics = compute_metrics(records, items)
    except KeyError as exc:
        print(
            f"RECEIPT_VERIFY_FAIL record names item_id {exc} absent from the corpus",
            file=sys.stderr,
        )
        return 1
    except ValueError as exc:
        print(f"RECEIPT_VERIFY_FAIL {exc}", file=sys.stderr)
        return 1

    print("--- metrics (recomputed) ---")
    for name in METRIC_NAMES:
        print(_fmt(name, metrics[name]))
    print("RECEIPT_VERIFY_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
