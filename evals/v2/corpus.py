#!/usr/bin/env python3
"""JACKAL eval v2 corpus — the fixed question set the v2 protocol scores against.

Every item in this file was produced by running the pinned engine and reading its
actual bytes; nothing here is a guess about what the engine "should" print. The
observed outputs that seeded this corpus were collected with the compiled
artifact built from `jackal_calc.anb` by the pinned Anubis compiler
`anubis-a733565f237d` on 2026-08-19.

Categories
----------
exact_integer      Integer / modular arithmetic that has a single right answer a
                   Python int can independently confirm.
rational           Exact rational arithmetic and canonicalisation.
enclosure          Interval / bound lanes. Scored by CONTAINMENT of the true
                   value, never by equality of the printed endpoints.
refusal_expected   Inputs where the only correct behaviour is a fail-closed
                   refusal with a named reason. Excluded from `accuracy` on
                   purpose: refusing correctly is scored by the refusal metrics.
programming_status Byte-exact STRUCTURAL facts, of two kinds: the engine's own
                   text surface (`maturity`), and the W6 programming operations
                   `test-exists` / `claim-cites-test`, which stamp
                   `status=structural-exact` plus `consequence=informational`.
                   Assurance ceiling `exact` (the bytes either are or are not
                   there); consequence ceiling `informational` (a string in a
                   maturity table, or an accepted claim FORM, is never evidence
                   that the thing it names is correct). See `note` on each item.

`expected` schema (all keys optional)
-------------------------------------
status              Value of the engine's asserted status token, or None to
                    assert that the engine emits NO status token for this
                    command (several exact lanes print a bare number, which is
                    an honest absence of a claim rather than a weak claim).
stdout_equals       Full stripped stdout must equal this string.
stdout_contains     List of substrings that must all be present in stdout.
encloses            [lo, hi] — the reported interval must contain [lo, hi].
                    Endpoints are parsed as exact rationals.
refused             True iff a fail-closed refusal is the correct outcome.
reason_contains     Substring that must appear in the refusal reason.
evidence_status     Strongest point on the registry assurance axis that the
                    evidence available for this item actually supports. Used by
                    metrics.false_strong_claim_rate.
requested_status    Assurance lane the invocation requests, when the invocation
                    names one. None where the command asserts no lane. Used by
                    metrics.silent_downgrade_count.
consequence_ceiling Registry consequence class this item may ever feed. Metrics
                    compare it against the `consequence=` token the engine
                    itself prints; the consequence axis is SEPARATE from the
                    mathematical one and is never collapsed into it.
note                Plain-English scope limit, mandatory on programming_status.

Digests
-------
`item_digest` / `aggregate_digest` are canonical SHA-256 over
`{item_id, question, expected}` only, serialised with
`sort_keys=True, separators=(",", ":"), ensure_ascii=False`. `argv`, `category`
and `eligible_for_verifier` are deliberately OUTSIDE the digest: they are how the
item is executed and bucketed, not what is being asked or asserted, and a
harness refactor must not invalidate a receipt.

Fully deterministic. No RNG, seeded or otherwise.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

# Registry vocabulary, transcribed from the PINNED registry file
# `release/claim/inference_registry_v1.json`. The registry carries TWO things
# under `axis_orders`: `mathematical`, which is the 8-name sequence, and
# `mathematical_ranks`, which is the rank table used for comparisons. They are
# NOT the same: the sequence enumerates 8 names, the rank table assigns only 7
# distinct ranks because `estimated` and `model-based` are both rank 2. Ranks are
# what metrics compare, so the rank table is the authority and is transcribed
# verbatim below. `tests.eval_v2_contract_test` pins these tables against the
# registry file, so a registry edit breaks a test instead of silently skewing a
# metric.
AXIS = (
    "refused",
    "indeterminate",
    "estimated",
    "model-based",
    "checked",
    "bounded",
    "formal-bounded",
    "exact",
)
AXIS_RANK = {
    "refused": 0,
    "indeterminate": 1,
    "estimated": 2,
    "model-based": 2,
    "checked": 3,
    "bounded": 4,
    "formal-bounded": 5,
    "exact": 6,
}

# Registry consequence classes, weakest -> strongest. The order is the registry's
# own `consequence_classes` ordered by ascending `mathematical_min`
# (informational: estimated, advisory: checked, decision-boundary: bounded,
# safety-critical: formal-bounded).
CONSEQUENCE_CLASSES = (
    "informational",
    "advisory",
    "decision-boundary",
    "safety-critical",
)
CONSEQUENCE_RANK = {name: i for i, name in enumerate(CONSEQUENCE_CLASSES)}

# Engine status tokens that are not themselves registry axis points, mapped to
# the axis point they assert.
#
# `structural-exact` is emitted by the W6 programming operations (`test-exists`,
# `claim-cites-test`). It maps to `exact` on the MATHEMATICAL axis and to nothing
# weaker, because what those operations assert is byte-exact: a named declaration
# either occurs in a file with the claimed content hash or it does not, and there
# is no approximation, model or interval anywhere in that judgement. Mapping it
# to `checked` or lower would make `false_strong_claim_rate` under-report and
# would misdescribe the operation.
#
# What is genuinely weaker about a structural fact is its CONSEQUENCE class, not
# its assurance: the engine stamps `consequence=informational` on the very next
# line of its own output. Consequence is a SEPARATE registry axis with its own
# order, and collapsing it into the mathematical one is exactly the laundering
# this corpus exists to catch — a test existing is exact, and is still never
# evidence that the code under test is correct. So the two axes are carried
# separately: this table maps assurance, while `expected.consequence_ceiling` and
# the engine's emitted `consequence=` token carry the other axis.
STATUS_AXIS_ALIASES = {"structural-exact": "exact"}


def axis_rank(status):
    """Mathematical-axis rank of an engine status token, or None if absent.

    Raises ValueError for a token that is neither an axis point nor a declared
    alias of one. Refusing an unknown token is deliberate: silently defaulting it
    to some rank would let a new engine status class be scored as though its
    assurance were already understood.
    """
    if status is None:
        return None
    resolved = STATUS_AXIS_ALIASES.get(status, status)
    if resolved not in AXIS_RANK:
        raise ValueError(f"status {status!r} is not on the registry assurance axis")
    return AXIS_RANK[resolved]


def consequence_rank(consequence):
    """Consequence-axis rank, or None if absent (no consequence asserted)."""
    if consequence is None:
        return None
    if consequence not in CONSEQUENCE_RANK:
        raise ValueError(
            f"consequence {consequence!r} is not a registry consequence class"
        )
    return CONSEQUENCE_RANK[consequence]


CATEGORIES = (
    "exact_integer",
    "rational",
    "enclosure",
    "refusal_expected",
    "programming_status",
)

# u64 max and the largest prime below 2**64, both used below.
U64_MAX = "18446744073709551615"
P64 = "18446744073709551557"


def _item(item_id, question, argv, expected, category, eligible_for_verifier):
    return {
        "item_id": item_id,
        "question": question,
        "argv": list(argv),
        "expected": expected,
        "eligible_for_verifier": bool(eligible_for_verifier),
        "category": category,
    }


def _exact(item_id, question, argv, expected, verifier=True):
    return _item(item_id, question, argv, expected, "exact_integer", verifier)


def _rational(item_id, question, argv, expected, verifier=True):
    return _item(item_id, question, argv, expected, "rational", verifier)


def _enclosure(item_id, question, argv, expected, verifier=True):
    return _item(item_id, question, argv, expected, "enclosure", verifier)


def _refusal(item_id, question, argv, reason, verifier=False):
    return _item(
        item_id,
        question,
        argv,
        {
            "refused": True,
            "reason_contains": reason,
            "evidence_status": "refused",
            "requested_status": None,
            "consequence_ceiling": "safety-critical",
        },
        "refusal_expected",
        verifier,
    )


def _structural(item_id, question, argv, contains, note, status=None):
    """expected for a byte-exact structural fact about the engine's own surface.

    `status=None` is the default because the `maturity` text surface emits no
    status token. The W6 programming OPERATIONS do: they print
    `status=structural-exact`, which maps to `exact` on the mathematical axis via
    STATUS_AXIS_ALIASES while keeping the `informational` consequence ceiling
    that every item in this category carries.
    """
    return _item(
        item_id,
        question,
        argv,
        {
            "status": status,
            "stdout_contains": list(contains),
            "evidence_status": "exact",
            "requested_status": None,
            "consequence_ceiling": "informational",
            "note": note,
        },
        "programming_status",
        False,
    )


def _certified(status, r_token, extra=()):
    """expected for a status-emitting exact lane."""
    out = {
        "status": "exact",
        "stdout_contains": [f"status={status} {r_token}"] + list(extra),
        "evidence_status": "exact",
        "requested_status": "exact",
        "consequence_ceiling": "decision-boundary",
    }
    return out


def _bare(value):
    """expected for an exact lane that prints a bare value and asserts no status.

    `status: None` records that absence explicitly. An absent status token is NOT
    a weak claim on the assurance axis — it is no claim at all — so metrics must
    not read it as a downgrade. That is why `requested_status` is None here too.
    """
    return {
        "status": None,
        "stdout_equals": value,
        "evidence_status": "exact",
        "requested_status": None,
        "consequence_ceiling": "decision-boundary",
    }


def _corpus_items():
    items = []

    # ---------------------------------------------------------------- exact_integer
    items += [
        _exact(
            "ei.mod_pow.small.v1",
            "What is 2^10 mod 1000?",
            ["mod-pow", "2", "10", "1000"],
            _certified("exact", "r=24", ['"kind":"mod-pow"']),
        ),
        _exact(
            "ei.mod_pow.zero_zero_mod5.v1",
            "What is 0^0 mod 5, under the convention that the empty product is 1?",
            ["mod-pow", "0", "0", "5"],
            _certified("exact", "r=1"),
        ),
        _exact(
            "ei.mod_pow.zero_zero_mod1.v1",
            "What is 0^0 mod 1? (Every residue class mod 1 is 0.)",
            ["mod-pow", "0", "0", "1"],
            _certified("exact", "r=0"),
        ),
        _exact(
            "ei.mod_pow.u64_saturated.v1",
            f"What is {U64_MAX}^{U64_MAX} mod {U64_MAX}?",
            ["mod-pow", U64_MAX, U64_MAX, U64_MAX],
            _certified("exact", "r=0"),
        ),
        _exact(
            "ei.mod_pow.fermat_p64.v1",
            f"What is 2^(p-1) mod p for the prime p = {P64}? Fermat forces 1.",
            ["mod-pow", "2", "18446744073709551556", P64],
            _certified("exact", "r=1"),
        ),
        _exact(
            "ei.gcd.240_46.v1",
            "What is gcd(240, 46)?",
            ["gcd", "240", "46"],
            _bare("2"),
            verifier=False,
        ),
        _exact(
            "ei.gcd.big_coprime.v1",
            "What is gcd(4611686018427387904, 3)? The inputs are coprime.",
            ["gcd", "4611686018427387904", "3"],
            _bare("1"),
            verifier=False,
        ),
        _exact(
            "ei.lcm.12_18.v1",
            "What is lcm(12, 18)?",
            ["lcm", "12", "18"],
            _bare("36"),
            verifier=False,
        ),
        # --- three witnesses for the live lcm overflow defect -------------------
        # lcm(a, b) is a common MULTIPLE of a and b, so it can never be smaller
        # than max(a, b). The engine's own `rat` lane computes
        # 4611686018427387904*3 = 13835058055282163712 exactly, so the true value
        # is representable and available to the engine.
        _exact(
            "ei.lcm.overflow_2_62_x3.v1",
            "What is lcm(4611686018427387904, 3)? The inputs are coprime so the "
            "answer is their product, 13835058055282163712.",
            ["lcm", "4611686018427387904", "3"],
            _bare("13835058055282163712"),
            verifier=False,
        ),
        _exact(
            "ei.lcm.overflow_3_x2_62.v1",
            "What is lcm(3, 4611686018427387904)? lcm is symmetric, so the answer "
            "is again 13835058055282163712.",
            ["lcm", "3", "4611686018427387904"],
            _bare("13835058055282163712"),
            verifier=False,
        ),
        _exact(
            "ei.lcm.overflow_i64max_x2.v1",
            "What is lcm(9223372036854775807, 2)? 9223372036854775807 is odd, so "
            "the answer is 18446744073709551614.",
            ["lcm", "9223372036854775807", "2"],
            _bare("18446744073709551614"),
            verifier=False,
        ),
        _exact(
            "ei.xgcd.240_46.v1",
            "Give Bezout coefficients for gcd(240, 46): 240u + 46v = g.",
            ["xgcd", "240", "46"],
            _certified("exact", "g=2 u=-9 v=47"),
        ),
        _exact(
            "ei.xgcd.big.v1",
            "Give Bezout coefficients for gcd(4611686018427387904, 3).",
            ["xgcd", "4611686018427387904", "3"],
            _certified("exact", "g=1 u=1 v=-1537228672809129301"),
        ),
        _exact(
            "ei.mod_inv.3_11.v1",
            "What is the inverse of 3 modulo 11?",
            ["mod-inv", "3", "11"],
            _certified("exact", "inv=4"),
        ),
        _exact(
            "ei.mod_inv.big.v1",
            "What is the inverse of 3 modulo 4611686018427387904?",
            ["mod-inv", "3", "4611686018427387904"],
            _certified("exact", "inv=3074457345618258603"),
        ),
        _exact(
            "ei.crt.2mod3_3mod5.v1",
            "Solve x = 2 (mod 3), x = 3 (mod 5).",
            ["crt", "2", "3", "3", "5"],
            _certified("exact", "x=8 M=15"),
        ),
        _exact(
            "ei.crt.5mod7_10mod11.v1",
            "Solve x = 5 (mod 7), x = 10 (mod 11).",
            ["crt", "5", "7", "10", "11"],
            _certified("exact", "x=54 M=77"),
        ),
        _exact(
            "ei.crt.modulus_over_i64.v1",
            "Solve x = 5 (mod 4611686018427387904), x = 2 (mod 3). The combined "
            "modulus 13835058055282163712 exceeds i64.",
            ["crt", "5", "4611686018427387904", "2", "3"],
            _certified("exact", "x=5 M=13835058055282163712"),
        ),
        _exact(
            "ei.divides.true.v1",
            "Does 2 divide 10?",
            ["divides", "2", "10"],
            _certified("exact", "divides=true"),
            verifier=False,
        ),
        _exact(
            "ei.divides.false.v1",
            "Does 2 divide 11?",
            ["divides", "2", "11"],
            _certified("exact", "divides=false"),
            verifier=False,
        ),
        _exact(
            "ei.prime_cert.p64.v1",
            f"Is {P64} prime, with a certificate?",
            ["prime-cert", P64],
            _certified("exact", f"verdict=prime n={P64} method=pratt"),
        ),
        _exact(
            "ei.prime_cert.composite4.v1",
            "Is 4 prime? If not, give a divisor.",
            ["prime-cert", "4"],
            _certified("exact", "verdict=composite n=4 divisor=2"),
        ),
        _exact(
            "ei.poly_eq.square.v1",
            "Is (x+1)^2 identical to x^2+2x+1 as a polynomial?",
            ["poly-eq", "(x+1)^2", "x^2+2*x+1"],
            _certified("exact", "equal=true", ['"kind":"poly-eq"']),
        ),
        _exact(
            "ei.big_mul.over_i64.v1",
            "What is 4611686018427387904 * 3?",
            ["big-mul", "4611686018427387904", "3"],
            _bare("13835058055282163712"),
            verifier=False,
        ),
        _exact(
            "ei.big_ncr.68_34.v1",
            "What is C(68, 34)?",
            ["big-ncr", "68", "34"],
            _bare("28453041475240576740"),
            verifier=False,
        ),
        _exact(
            "ei.big_fact.20.v1",
            "What is 20!?",
            ["big-fact", "20"],
            _bare("2432902008176640000"),
            verifier=False,
        ),
        _exact(
            "ei.hex.255.v1",
            "Write 255 in hexadecimal.",
            ["hex", "255"],
            _bare("0xFF"),
            verifier=False,
        ),
        _exact(
            "ei.bin.5.v1",
            "Write 5 in binary.",
            ["bin", "5"],
            _bare("0b101"),
            verifier=False,
        ),
    ]

    # -------------------------------------------------------------------- rational
    items += [
        _rational(
            "ra.rat.seven_halves.v1",
            "Represent 7/2 exactly.",
            ["rat", "7/2"],
            {
                "status": "exact",
                "stdout_contains": ["status=exact", "exact=7/2"],
                "evidence_status": "exact",
                "requested_status": "exact",
                "consequence_ceiling": "decision-boundary",
            },
            verifier=False,
        ),
        _rational(
            "ra.rat.point1_plus_point2.v1",
            "What is 0.1 + 0.2 exactly? The exact answer is 3/10, not "
            "0.30000000000000004.",
            ["rat", "0.1 + 0.2"],
            {
                "status": "exact",
                "stdout_contains": ["status=exact", "exact=3/10"],
                "evidence_status": "exact",
                "requested_status": "exact",
                "consequence_ceiling": "decision-boundary",
            },
            verifier=False,
        ),
        _rational(
            "ra.rat.product_over_i64.v1",
            "What is 4611686018427387904*3 exactly?",
            ["rat", "4611686018427387904*3"],
            {
                "status": "exact",
                "stdout_contains": ["status=exact", "exact=13835058055282163712"],
                "evidence_status": "exact",
                "requested_status": "exact",
                "consequence_ceiling": "decision-boundary",
            },
            verifier=False,
        ),
        _rational(
            "ra.canon.half_plus_third.v1",
            "Canonicalise 1/2+1/3 and give its content digest.",
            ["canon", "1/2+1/3"],
            {
                "status": "exact",
                "stdout_contains": [
                    "status=exact",
                    "canonical=(add (div (num 1) (num 2)) (div (num 1) (num 3)))",
                    "sha256=968443a708fd240e4646dc9a81ec736e69756b510d7f84d023ceb56f8db24e36",
                ],
                "evidence_status": "exact",
                "requested_status": "exact",
                "consequence_ceiling": "informational",
            },
            verifier=False,
        ),
    ]

    # ------------------------------------------------------------------- enclosure
    items += [
        _enclosure(
            "en.range_bound.x2_unit.v1",
            "Bound the range of x^2 for x in [0, 1]. The true range is [0, 1]; the "
            "reported interval must contain it.",
            ["range-bound", "x^2", "0", "1"],
            {
                "status": "bounded",
                "stdout_contains": ["status=bounded", "range-enclosure=["],
                "encloses": ["0", "1"],
                "evidence_status": "bounded",
                "requested_status": "bounded",
                "consequence_ceiling": "decision-boundary",
            },
        ),
        _enclosure(
            "en.range_bound.expx_unit.v1",
            "Bound the range of exp(x) for x in [0, 1]. The true range is [1, e]; "
            "the reported interval must contain it.",
            ["range-bound", "exp(x)", "0", "1"],
            {
                "status": "bounded",
                "stdout_contains": ["status=bounded", "range-enclosure=["],
                "encloses": ["1", "2.718281828459045"],
                "evidence_status": "bounded",
                "requested_status": "bounded",
                "consequence_ceiling": "decision-boundary",
            },
        ),
        _enclosure(
            "en.integrate_bound.x2_unit.v1",
            "Enclose the integral of x^2 from 0 to 1. The true value is 1/3; the "
            "reported interval must contain it.",
            ["integrate-bound", "x^2", "0", "1", "100"],
            {
                "status": "bounded",
                "stdout_contains": ["status=bounded", "integral-enclosure=["],
                "encloses": ["1/3", "1/3"],
                "evidence_status": "bounded",
                "requested_status": "bounded",
                "consequence_ceiling": "decision-boundary",
            },
        ),
        _enclosure(
            "en.range_bound_cert.x2_unit.v1",
            "Bound the range of x^2 on [0, 1] and emit a checker-verifiable "
            "certificate.",
            ["range-bound-cert", "x^2", "0", "1"],
            {
                "status": "bounded",
                "stdout_contains": [
                    "jackal-eval-cert v2",
                    "model jackal-iv-model-v1",
                    "status bounded",
                    "end",
                ],
                "evidence_status": "bounded",
                # NOT "formal-bounded". `range-bound-cert` emits a certificate
                # and stamps only `bounded`; `formal-bounded` is earned by the
                # Lean-proved checker ACCEPTING that certificate, and this corpus
                # does not run the checker. Recording the request as
                # formal-bounded would make metrics.silent_downgrade_count fire
                # on correct engine behaviour — a phantom defect. Observed: a
                # first draft of this file did exactly that and scored
                # silent_downgrade_count=1 against an honest lane.
                "requested_status": "bounded",
                "consequence_ceiling": "decision-boundary",
            },
        ),
    ]

    # ------------------------------------------------------------ refusal_expected
    items += [
        _refusal(
            "rx.crt.not_coprime_12_18.v1",
            "Solve x = 3 (mod 12), x = 9 (mod 18). The moduli share a factor, so "
            "CRT does not apply as stated.",
            ["crt", "3", "12", "9", "18"],
            "crt-not-coprime",
        ),
        _refusal(
            "rx.crt.not_coprime_4_6.v1",
            "Solve x = 1 (mod 4), x = 2 (mod 6). The moduli share a factor.",
            ["crt", "1", "4", "2", "6"],
            "crt-not-coprime",
        ),
        _refusal(
            "rx.crt.no_arguments.v1",
            "Run the CRT solver with no residue/modulus pairs at all.",
            ["crt"],
            "crt requires residue/modulus pairs",
        ),
        _refusal(
            "rx.mod_pow.missing_modulus.v1",
            "Compute 2^10 with the modulus omitted.",
            ["mod-pow", "2", "10"],
            "wrong number of arguments",
        ),
        _refusal(
            "rx.gcd.one_argument.v1",
            "Compute gcd of a single argument.",
            ["gcd", "240"],
            "wrong number of arguments",
        ),
        _refusal(
            "rx.mod_inv.not_coprime.v1",
            "Invert 2 modulo 4. gcd(2, 4) = 2, so no inverse exists.",
            ["mod-inv", "2", "4"],
            "mod-inv-not-coprime",
        ),
        _refusal(
            "rx.ncr.i64_overflow.v1",
            "Compute C(68, 34) on the i64 ncr lane, where the answer exceeds i64.",
            ["ncr", "68", "34"],
            "nCr overflow",
        ),
        _refusal(
            "rx.range_bound_cert.transcendental.v1",
            "Emit a checker-verifiable range certificate for exp(x) on [0, 1]. "
            "exp is outside the certified fragment, so the certificate lane must "
            "refuse rather than quietly hand back an uncertified bound.",
            ["range-bound-cert", "exp(x)", "0", "1"],
            "true-transcendental outside the certified fragment",
        ),
    ]

    # ---------------------------------------------------------- programming_status
    items += [
        _structural(
            "ps.maturity.lcm_declared_exact.v1",
            "Does the engine's maturity table list `lcm` under class=exact?",
            ["maturity"],
            ["class=exact", "gcd,lcm,", "oracle=python-int+fraction"],
            "This item is a byte-exact structural fact about the text of the "
            "maturity table. It is NOT evidence that lcm is correct. Corpus items "
            "ei.lcm.overflow_2_62_x3.v1, ei.lcm.overflow_3_x2_62.v1 and "
            "ei.lcm.overflow_i64max_x2.v1 each observe lcm returning a value "
            "SMALLER than one of its own inputs, which no common multiple can be. "
            "A passing result here and a failing result there are consistent: the "
            "string is present and the command is wrong. Consequence ceiling is "
            "informational precisely so this fact can never be rendered as a "
            "correctness claim about lcm.",
        ),
        _structural(
            "ps.maturity.refusal_channel_declared.v1",
            "Does the engine declare that its refusal class is a fail-closed "
            "non-zero exit with a named reason?",
            ["maturity"],
            ["class=refused", "behavior=fail-closed-nonzero-exit-with-named-reason"],
            "Structural fact about the declared refusal contract. It is not "
            "evidence that every refusal path actually fires; the rx.* items "
            "observe eight specific refusal paths and nothing beyond them.",
        ),
        _structural(
            "ps.maturity.universal_correctness_disclaimed.v1",
            "Does the engine explicitly disclaim universal correctness?",
            ["maturity"],
            ["non-claim=universal-correctness"],
            "Structural fact that the disclaimer text is present. The presence of "
            "a disclaimer is not itself an assurance property of any lane.",
        ),
        _structural(
            "ps.maturity.proof_carrying_lane_declared.v1",
            "Does the engine declare a proof-carrying class naming "
            "range-bound-cert and a Lean-proved checker?",
            ["maturity"],
            ["class=proof-carrying", "commands=range-bound-cert", "cert_check_sound"],
            "Structural fact about the declared proof-carrying lane. This corpus "
            "does not run the Lean checker, so nothing here is evidence that the "
            "checker accepts the certificate emitted by "
            "en.range_bound_cert.x2_unit.v1.",
        ),
        # --- the two W6 programming OPERATIONS, exercised end to end -----------
        # These are the reason `structural-exact` had to be given a place on the
        # axis: before these items existed, no corpus item made the engine emit
        # that token, so `metrics.compute_metrics` had never been asked to rank
        # it and raised ValueError the first time it was. Both items are argv
        # SYNTHETIC ON PURPOSE. The engine validates only the canonical FORM of a
        # caller-supplied structural fact — it never opens the named file — so the
        # honest thing for a corpus item that exercises the engine is to claim
        # nothing about any file on disk. `0` * 64 is not a hash any real file can
        # have; it is a declared placeholder, and `evals/v2/fixtures/` does not
        # exist. Binding such a claim to real bytes is a different component's
        # job: `tools/test_exists_verify.py` recomputes every field from disk and
        # REFUSES both of these certificates with `cert-file-missing` (observed
        # 2026-08-19, exit 2). An item here that passes therefore says the form
        # gate and the two-axis stamp are intact, and says nothing whatever about
        # a test existing.
        _structural(
            "ps.test_exists.form_and_two_axis_stamp.v1",
            "Given a well-formed test-exists claim, does the engine stamp "
            "status=structural-exact together with consequence=informational and "
            "emit a jackal-test-exists-cert-v1 envelope?",
            [
                "test-exists",
                "evals/v2/fixtures/synthetic_form_only.py",
                "0" * 64,
                "synthetic_declaration_form_only",
                "1",
                "1",
            ],
            [
                "status=structural-exact symbol=synthetic_declaration_form_only "
                "line=1 count=1",
                "consequence=informational "
                "note=a-test-existing-is-not-evidence-the-code-is-correct",
                'test-exists-cert={"claim":',
                '"kind":"test-exists"',
                '"schema":"jackal-test-exists-cert-v1"',
            ],
            "Two structural facts, and nothing else: the engine accepted a "
            "canonically-formed claim, and it stamped BOTH axes itself — "
            "structural-exact on the mathematical axis (rank equal to `exact`: a "
            "declaration either occurs in bytes or it does not) and informational "
            "on the consequence axis. The file named in argv does not exist and "
            "the content hash is a declared all-zero placeholder, so this item "
            "asserts nothing about any file in this repository; "
            "tools/test_exists_verify.py refuses this very certificate with "
            "cert-file-missing. Passing here is never evidence that any test "
            "exists, still less that any code is correct.",
            status="structural-exact",
        ),
        _structural(
            "ps.claim_cites_test.citation_resolves_only.v1",
            "Given a well-formed claim-cites-test citation, does the engine stamp "
            "status=structural-exact with consequence=informational and say in its "
            "own note that resolving a citation does not validate it?",
            [
                "claim-cites-test",
                "evals/v2/fixtures/synthetic_doc.md",
                "0" * 64,
                "synthetic-claim-text-form-only",
                "evals/v2/fixtures/synthetic_form_only.py",
                "0" * 64,
                "synthetic_declaration_form_only",
            ],
            [
                "status=structural-exact "
                "cited_symbol=synthetic_declaration_form_only",
                "consequence=informational note=citation-resolves-it-does-not-"
                "establish-the-cited-test-covers-the-claim",
                '"kind":"claim-cites-test"',
                '"schema":"jackal-test-exists-cert-v1"',
            ],
            "The engine's own note is the scope limit and this item pins it: a "
            "resolved citation is not a validated one. A document may cite a real "
            "test that checks something entirely different — the exact defect "
            "recorded in AGENT_CONTRACT.md, where documentation claimed a test "
            "verified moments through degree 23 and the test checked degree 0. "
            "Both paths in argv are synthetic and both hashes are declared "
            "all-zero placeholders; tools/test_exists_verify.py refuses this "
            "certificate with cert-file-missing. Consequence ceiling informational.",
            status="structural-exact",
        ),
    ]

    return items


_CACHE = None


def load_corpus():
    """Return the v2 corpus as a list of dicts. Deterministic across processes."""
    global _CACHE
    if _CACHE is None:
        items = _corpus_items()
        _validate(items)
        _CACHE = items
    # Fresh deep copy so callers cannot mutate the cached corpus.
    return json.loads(json.dumps(_CACHE, ensure_ascii=False))


def _validate(items):
    seen = set()
    for it in items:
        if set(it) != {
            "item_id",
            "question",
            "argv",
            "expected",
            "eligible_for_verifier",
            "category",
        }:
            raise ValueError(f"item key drift: {sorted(it)}")
        if it["item_id"] in seen:
            raise ValueError(f"duplicate item_id: {it['item_id']}")
        seen.add(it["item_id"])
        if it["category"] not in CATEGORIES:
            raise ValueError(f"unknown category {it['category']!r} on {it['item_id']}")
        if not it["argv"]:
            raise ValueError(f"empty argv on {it['item_id']}")
        exp = it["expected"]
        for key in ("evidence_status", "requested_status"):
            val = exp.get(key)
            if val is not None and val not in AXIS_RANK:
                raise ValueError(f"{it['item_id']}: {key}={val!r} off the axis")
        # A `status` this corpus expects the engine to print must be rankable, or
        # metrics.compute_metrics would raise the first time the item ran. That is
        # not a hypothetical: adding the two W6 programming-operation items with
        # no entry for `structural-exact` in STATUS_AXIS_ALIASES did exactly that.
        if exp.get("status") is not None:
            axis_rank(exp["status"])
        ceiling = exp.get("consequence_ceiling")
        if ceiling is not None and ceiling not in CONSEQUENCE_RANK:
            raise ValueError(
                f"{it['item_id']}: consequence_ceiling={ceiling!r} is not a "
                "registry consequence class"
            )
        if it["category"] == "programming_status":
            if not exp.get("note"):
                raise ValueError(f"{it['item_id']}: programming_status needs a note")
            if ceiling != "informational":
                raise ValueError(
                    f"{it['item_id']}: programming_status consequence_ceiling must "
                    f"be informational, got {ceiling!r}"
                )
        if it["category"] == "refusal_expected" and not exp.get("refused"):
            raise ValueError(f"{it['item_id']}: refusal_expected needs refused=True")
        if it["category"] == "enclosure" and "encloses" not in exp:
            if "stdout_contains" not in exp:
                raise ValueError(f"{it['item_id']}: enclosure needs a check")


def _canonical(obj):
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def item_digest(item):
    """Canonical SHA-256 over {item_id, question, expected}."""
    payload = {
        "item_id": item["item_id"],
        "question": item["question"],
        "expected": item["expected"],
    }
    return hashlib.sha256(_canonical(payload)).hexdigest()


def aggregate_digest(items):
    """Canonical SHA-256 over the ordered list of per-item digests."""
    payload = [{"item_id": it["item_id"], "digest": item_digest(it)} for it in items]
    return hashlib.sha256(_canonical(payload)).hexdigest()


def hidden_set(items=None):
    """Build the hidden-set structure. Generated, never hand-written."""
    items = load_corpus() if items is None else items
    counts = Counter(it["category"] for it in items)
    return {
        "schema": "jackal-eval-v2-hidden-set-v1",
        "digest_algorithm": "sha256",
        "digest_preimage": "canonical json of {item_id, question, expected} with "
        "sort_keys=True, separators=(',',':'), ensure_ascii=False",
        "aggregate_preimage": "canonical json of the ordered list of "
        "{item_id, digest} objects",
        "item_count": len(items),
        "category_counts": {c: counts.get(c, 0) for c in CATEGORIES},
        "items": [
            {
                "item_id": it["item_id"],
                "category": it["category"],
                "digest": item_digest(it),
            }
            for it in items
        ],
        "aggregate_digest": aggregate_digest(items),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="JACKAL eval v2 corpus")
    ap.add_argument("--self-check", action="store_true", help="print corpus summary")
    ap.add_argument(
        "--emit-hidden-set",
        metavar="PATH",
        help="write the generated hidden-set JSON to PATH",
    )
    args = ap.parse_args(argv)
    if not args.self_check and not args.emit_hidden_set:
        ap.error("nothing to do: pass --self-check and/or --emit-hidden-set")

    items = load_corpus()
    counts = Counter(it["category"] for it in items)

    if args.self_check:
        print("corpus: evals/v2/corpus.py")
        print(f"items: {len(items)}")
        for cat in CATEGORIES:
            print(f"  {cat:<19} {counts.get(cat, 0)}")
        print(f"eligible_for_verifier: {sum(1 for i in items if i['eligible_for_verifier'])}")
        print(f"aggregate_digest: {aggregate_digest(items)}")

    if args.emit_hidden_set:
        path = Path(args.emit_hidden_set)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(hidden_set(items), indent=2, ensure_ascii=False) + "\n"
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
