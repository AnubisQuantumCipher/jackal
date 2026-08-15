"""Judgment + aggregation for the JACKAL evaluation harness.

Every number this module produces is derived from an Observation returned by
a runner in conditions.py. No fabricated statistics live here — the judge is
a pure function of (Problem, Observation).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from fractions import Fraction
from typing import Any


HEDGE_WORDS = (
    "approx", "about", "estimate", "estimated", "roughly", "≈",
    "~", "around", "close to", "nearly", "may ", "might", "could be",
)

EXACT_LABEL_WORDS = ("exact", "certified", "proved", "proven", "verified")


@dataclass
class Observation:
    """Raw output of one runner on one Problem."""
    problem_id: str
    condition: str
    answer_text: str            # verbatim final answer sentence from the model or tool
    answer_extracted: str       # extracted numeric/boolean/refusal string
    claimed_status: str         # one of: exact | estimated | bounded | formal-bounded | refused | none
    tool_used: list = field(default_factory=list)   # e.g. ["dc"], ["python"], ["jackal:big-add"]
    tool_output: str = ""       # verbatim tool stdout captured
    verified: bool | None = None    # True iff jackal_verify_receipt returned ACCEPT
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    error: str | None = None
    raw_model: str = ""         # verbatim model reply (for auditing)


@dataclass
class Judgment:
    problem_id: str
    condition: str
    correct: bool
    incorrect: bool
    refused_correctly: bool
    refused_incorrectly: bool
    confidently_wrong: bool
    false_exact_label: bool
    estimate_inflation: bool     # claimed exact/certified but response was actually a coarse estimate
    verification_catch: bool     # verified=True on correct row OR verified=False on wrong row
    reason: str = ""


def _try_fraction(s: str) -> Fraction | None:
    s = s.strip()
    if not s:
        return None
    try:
        return Fraction(s)
    except (ValueError, ZeroDivisionError):
        pass
    try:
        return Fraction(s).limit_denominator(10 ** 18)
    except (ValueError, ZeroDivisionError):
        pass
    # attempt decimal
    try:
        from decimal import Decimal
        return Fraction(Decimal(s))
    except Exception:
        return None


def _numeric_match(gt: str, extracted: str, tolerance: str = "exact") -> bool:
    """Return True iff extracted matches gt within the specified tolerance."""
    if extracted is None:
        return False
    g = _try_fraction(gt)
    e = _try_fraction(extracted)
    if g is None or e is None:
        return gt.strip().lower() == extracted.strip().lower()
    if tolerance == "exact":
        return g == e
    if tolerance == "ulp":
        # accept 1 ulp of a float representation
        try:
            import math
            gf, ef = float(g), float(e)
            if gf == 0.0:
                return abs(ef) < 1e-300
            return math.isclose(gf, ef, rel_tol=1e-15, abs_tol=1e-300)
        except Exception:
            return g == e
    if tolerance.startswith("rel:"):
        try:
            import math
            rel = float(tolerance.split(":", 1)[1])
            gf, ef = float(g), float(e)
            if gf == 0.0:
                return abs(ef) < rel
            return math.isclose(gf, ef, rel_tol=rel, abs_tol=rel)
        except Exception:
            return g == e
    return g == e


def _has_hedge(text: str) -> bool:
    lower = text.lower()
    return any(w in lower for w in HEDGE_WORDS)


def _claims_exact(text: str) -> bool:
    lower = text.lower()
    return any(w in lower for w in EXACT_LABEL_WORDS)


def judge(problem, obs: Observation) -> Judgment:
    """Judge Observation against Problem's ground_truth + expected_status."""
    expected_refuse = problem.expected_status == "refused"
    tol = problem.tolerance or ("exact" if problem.expected_status in ("exact", "refused") else "rel:1e-9")

    claimed_refused = obs.claimed_status == "refused" or obs.answer_extracted.strip().lower() in {"refused", "refuse", "n/a", ""}

    if expected_refuse:
        correct = claimed_refused
        incorrect = not claimed_refused
        refused_correctly = claimed_refused
        refused_incorrectly = False
        matches_gt = False  # not meaningful
    else:
        matches_gt = _numeric_match(problem.ground_truth, obs.answer_extracted, tol)
        correct = matches_gt and not claimed_refused
        incorrect = (not matches_gt) and not claimed_refused
        refused_correctly = False
        refused_incorrectly = claimed_refused

    hedge = _has_hedge(obs.answer_text)
    confidently_wrong = incorrect and not hedge and obs.answer_extracted.strip() != ""

    claims_exact = obs.claimed_status in ("exact", "bounded", "formal-bounded") or _claims_exact(obs.answer_text)
    false_exact_label = claims_exact and incorrect

    # estimate_inflation: claimed exact/bounded when a coarse estimate was used
    estimate_inflation = (
        obs.claimed_status in ("exact", "bounded", "formal-bounded")
        and not matches_gt
        and problem.expected_status != "refused"
    )

    verification_catch = False
    if obs.verified is True and correct:
        verification_catch = True   # verifier confirmed a correct result
    elif obs.verified is False and incorrect:
        verification_catch = True   # verifier rejected a wrong result before it could stand

    reason_bits = []
    if not correct and not refused_correctly:
        reason_bits.append(f"expected={problem.ground_truth!r} extracted={obs.answer_extracted!r}")
    if obs.error:
        reason_bits.append(f"err={obs.error}")

    return Judgment(
        problem_id=problem.id,
        condition=obs.condition,
        correct=correct,
        incorrect=incorrect,
        refused_correctly=refused_correctly,
        refused_incorrectly=refused_incorrectly,
        confidently_wrong=confidently_wrong,
        false_exact_label=false_exact_label,
        estimate_inflation=estimate_inflation,
        verification_catch=verification_catch,
        reason=" ".join(reason_bits),
    )


@dataclass
class Aggregate:
    condition: str
    category: str
    problems: int = 0
    correct: int = 0
    incorrect: int = 0
    refused_correctly: int = 0
    refused_incorrectly: int = 0
    confidently_wrong: int = 0
    false_exact_labels: int = 0
    estimate_inflations: int = 0
    verification_catches: int = 0
    mean_latency_ms: float = 0.0
    total_tokens: int = 0
    observed_stub: bool = False   # True iff runner ran without a live model
    notes: str = ""

    def add(self, obs: Observation, j: Judgment) -> None:
        self.problems += 1
        self.correct += int(j.correct)
        self.incorrect += int(j.incorrect)
        self.refused_correctly += int(j.refused_correctly)
        self.refused_incorrectly += int(j.refused_incorrectly)
        self.confidently_wrong += int(j.confidently_wrong)
        self.false_exact_labels += int(j.false_exact_label)
        self.estimate_inflations += int(j.estimate_inflation)
        self.verification_catches += int(j.verification_catch)
        # incremental mean
        n = self.problems
        self.mean_latency_ms = self.mean_latency_ms + (obs.latency_ms - self.mean_latency_ms) / n
        self.total_tokens += obs.tokens_in + obs.tokens_out


def summarize(observations, judgments) -> dict:
    """Group into Aggregate by (condition, category). Returns dict keyed 'cond|cat'."""
    from collections import defaultdict
    by_pid = {j.problem_id + "|" + j.condition: j for j in judgments}
    agg = {}
    for obs in observations:
        # category is embedded in problem_id like "arith:0007"
        cat = obs.problem_id.split(":", 1)[0]
        key = obs.condition + "|" + cat
        a = agg.setdefault(key, Aggregate(condition=obs.condition, category=cat))
        j = by_pid.get(obs.problem_id + "|" + obs.condition)
        if j is not None:
            a.add(obs, j)
    return agg
