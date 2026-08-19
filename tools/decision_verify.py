#!/usr/bin/env python3
"""Independent checker for `jackal-decision-cert-v1`.

The engine selects an option and records a margin. This checker does not take
either on trust: it recomputes the selection, the runner-up, and the margin
from the certificate's own `options` array and refuses on any disagreement.
That is what makes the certificate sound. A caller who edits `selected` to name
a different option, or inflates `margin` to manufacture a comfortable-looking
decision, cannot mint an accepted claim.

Verdicts are printed on the final line as `ACCEPT` or `REFUSE <reason-class>`,
and the exit status is 0 only for ACCEPT.

Scope, stated as a permanent nonclaim
-------------------------------------
This checker establishes that, given the declared numeric criterion and the
declared option values, the recorded selection is the argmax (or argmin) and
the recorded margin is exactly the gap to the runner-up. It does NOT establish:

  * that the declared criterion is the right thing to optimise;
  * that the declared values are true, current, or measured rather than guessed;
  * that the selected option is better, preferable, or more worthwhile.

The last point is the reason `require_measurable_criterion` exists in the engine
and is mirrored here. A decision matrix can order options by a stated,
recomputable quantity. Ranking on preference, goodness, or worth is a value
judgment, and rendering one as a mathematical selection is precisely the
laundering this pack refuses. Such certificates are refused, not answered.

A zero margin is refused rather than reported: a tie at the top is a coin flip,
and a coin flip wearing a certificate is worse than no certificate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

SCHEMA = "jackal-decision-cert-v1"
KIND = "decision-rank"
ENVELOPE_PREFIX = "decision-cert="
MIN_OPTIONS = 2
MAX_OPTIONS = 6
SENSES = ("max", "min")

# Byte-identical to `require_measurable_criterion` in jackal_calc.anb, in the
# same order, matched as a substring against the ASCII-lowercased criterion.
# If the engine's list and this list ever diverge, the engine and its
# independent checker disagree about what is admissible, and the pack is
# unsound. Change both or neither.
VALUE_JUDGMENT_WORDS = (
    "better", "best", "worse", "worst", "good", "bad", "should", "prefer",
    "worth", "moral", "ethical", "fair", "right", "wrong", "beauty", "nicer",
    "nicest", "superior", "inferior", "ought",
)

_SYMBOL_RE = re.compile(r"[A-Za-z0-9_]{1,256}")
_INTEGER_RE = re.compile(r"-?(?:0|[1-9][0-9]{0,63})")


class Refusal(Exception):
    def __init__(self, reason_class: str, detail: str = "") -> None:
        super().__init__(f"{reason_class}{': ' + detail if detail else ''}")
        self.reason_class = reason_class
        self.detail = detail


def _require_symbol(value: object, field: str) -> str:
    if not isinstance(value, str) or _SYMBOL_RE.fullmatch(value) is None:
        raise Refusal("cert-field-shape", f"{field} is not a [A-Za-z0-9_] identifier")
    return value


def _require_integer(value: object, field: str) -> int:
    if not isinstance(value, str) or _INTEGER_RE.fullmatch(value) is None:
        raise Refusal("cert-field-shape", f"{field} is not a canonical decimal integer")
    if value == "-0":
        raise Refusal("cert-field-shape", f"{field} is a non-canonical negative zero")
    return int(value)


def require_measurable_criterion(criterion: str) -> None:
    lowered = criterion.lower()
    for word in VALUE_JUDGMENT_WORDS:
        if word in lowered:
            raise Refusal(
                "cert-value-judgment",
                f"criterion {criterion!r} contains {word!r}: a value judgment is "
                "not a measurable quantity",
            )


def _parse_options(value: object) -> tuple[list[str], list[int]]:
    if not isinstance(value, list):
        raise Refusal("cert-claim-shape", "options is not an array")
    if not MIN_OPTIONS <= len(value) <= MAX_OPTIONS:
        raise Refusal(
            "cert-option-count",
            f"{len(value)} options outside the {MIN_OPTIONS}..{MAX_OPTIONS} bound",
        )
    labels: list[str] = []
    values: list[int] = []
    for index, option in enumerate(value):
        if not isinstance(option, dict):
            raise Refusal("cert-option-keys", f"options[{index}] is not an object")
        if set(option) != {"label", "value"}:
            raise Refusal(
                "cert-option-keys", f"options[{index}] must have exactly label/value"
            )
        label = _require_symbol(option["label"], f"options[{index}].label")
        if label in labels:
            raise Refusal("cert-duplicate-label", f"label {label!r} occurs twice")
        labels.append(label)
        values.append(_require_integer(option["value"], f"options[{index}].value"))
    return labels, values


def _select(values: list[int], sense: str) -> tuple[int, int]:
    """Recompute (best, runner_up) indices with the engine's first-wins ties.

    The engine improves on a strict comparison, so among equal extrema the
    lowest index wins. This mirrors that exactly; a different tie-break here
    would reject certificates the engine legitimately emits.
    """
    better = (lambda a, b: a > b) if sense == "max" else (lambda a, b: a < b)
    best = 0
    for index in range(1, len(values)):
        if better(values[index], values[best]):
            best = index
    runner = -1
    for index in range(len(values)):
        if index == best:
            continue
        if runner == -1 or better(values[index], values[runner]):
            runner = index
    return best, runner


def verify(raw: str) -> list[str]:
    payload = parse_envelope(raw)
    claim = payload["claim"]
    expected_keys = {
        "criterion",
        "decision_id",
        "margin",
        "options",
        "runner_up",
        "selected",
        "sense",
    }
    if set(claim) != expected_keys:
        raise Refusal("cert-claim-keys", f"expected exactly {sorted(expected_keys)}")

    _require_symbol(claim["decision_id"], "decision_id")
    criterion = _require_symbol(claim["criterion"], "criterion")
    require_measurable_criterion(criterion)

    sense = claim["sense"]
    if sense not in SENSES:
        raise Refusal("cert-sense-unknown", f"sense {sense!r} is not one of {SENSES}")

    labels, values = _parse_options(claim["options"])
    selected = _require_symbol(claim["selected"], "selected")
    runner_up = _require_symbol(claim["runner_up"], "runner_up")
    claimed_margin = _require_integer(claim["margin"], "margin")

    if selected not in labels:
        raise Refusal("cert-selected-not-an-option", f"{selected!r} is not in options")
    if runner_up not in labels:
        raise Refusal("cert-runner-up-not-an-option", f"{runner_up!r} is not in options")
    if selected == runner_up:
        raise Refusal("cert-runner-up-is-selected", "runner_up duplicates selected")

    best, runner = _select(values, sense)
    if labels[best] != selected:
        raise Refusal(
            "cert-selection-mismatch",
            f"selected claims {selected!r} but the {sense} of {dict(zip(labels, values))} "
            f"is {labels[best]!r}",
        )
    if labels[runner] != runner_up:
        raise Refusal(
            "cert-runner-up-mismatch",
            f"runner_up claims {runner_up!r} but recomputes to {labels[runner]!r}",
        )

    margin = values[best] - values[runner] if sense == "max" else values[runner] - values[best]
    if margin == 0:
        raise Refusal(
            "cert-margin-zero",
            f"{selected!r} and {runner_up!r} tie on {criterion}: a tie is not a decision",
        )
    if margin < 0:
        raise Refusal(
            "cert-margin-negative",
            f"recomputed margin {margin} is negative, so the selection is not extremal",
        )
    if margin != claimed_margin:
        raise Refusal(
            "cert-margin-mismatch",
            f"margin claimed {claimed_margin} but recomputes to {margin}",
        )
    return [
        f"options recomputed {dict(zip(labels, values))}",
        f"{sense} selection recomputed {labels[best]}, runner-up {labels[runner]}",
        f"margin recomputed {margin}",
        "NOTE: the declared criterion remains the caller's; this is NOT a claim it is the right one",
    ]


def parse_envelope(raw: str) -> dict:
    text = raw.strip()
    if text.startswith(ENVELOPE_PREFIX):
        text = text[len(ENVELOPE_PREFIX) :]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Refusal("cert-not-json", str(exc)) from exc
    if not isinstance(payload, dict):
        raise Refusal("cert-not-object", "certificate is not a JSON object")
    if set(payload) != {"claim", "kind", "schema", "witness"}:
        raise Refusal("cert-envelope-keys", "expected exactly claim/kind/schema/witness")
    if payload["schema"] != SCHEMA:
        raise Refusal("cert-schema-unexpected", f"schema {payload['schema']!r} != {SCHEMA}")
    if payload["kind"] != KIND:
        raise Refusal("cert-kind-unexpected", f"kind {payload['kind']!r} != {KIND}")
    if not isinstance(payload["claim"], dict):
        raise Refusal("cert-claim-shape", "claim is not an object")
    if payload["witness"] != {}:
        raise Refusal("cert-witness-unexpected", "v1 defines no witness fields")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cert", help="path to a file holding the certificate line")
    parser.add_argument("--stdin", action="store_true", help="read the certificate from stdin")
    args = parser.parse_args(argv)

    if bool(args.cert) == bool(args.stdin):
        print("REFUSE cert-input-ambiguous: pass exactly one of --cert or --stdin")
        return 2
    if args.stdin:
        raw = sys.stdin.read()
    else:
        with open(args.cert, encoding="utf-8") as handle:
            raw = handle.read()
    # Tolerate a full command transcript: take the envelope line if present.
    for line in raw.splitlines():
        if line.strip().startswith(ENVELOPE_PREFIX):
            raw = line
            break

    try:
        notes = verify(raw)
    except Refusal as refusal:
        print(f"REFUSE {refusal.reason_class}: {refusal.detail}".rstrip(": "))
        return 2
    for note in notes:
        print(f"  {note}")
    print("ACCEPT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
