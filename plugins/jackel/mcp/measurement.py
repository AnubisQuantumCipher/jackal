#!/usr/bin/python3 -B
"""Identity-pinned measurement and provenance tools for the JACKAL MCP server.

This module is not a standalone service.  The identity-pinned JACKAL wrapper
loads it in-process and supplies a callback into the same serialized runtime
backend used by every other JACKAL tool.  Each arithmetic result is echoed in
``delegated_to``.  If the runtime is unavailable or refuses, this layer refuses;
it never substitutes Python floating-point arithmetic.

WHAT THIS SUBSYSTEM ADDS — the gap it closes:

JACKAL is airtight on numerals that ANNOUNCE THEMSELVES as arithmetic. The
leak is the numerals that do not: unit conversions, percentages, date deltas,
currency comparisons. Each of those is an exact computation resting on a datum
that is NOT mathematics — a conversion factor, a tz rule, an exchange rate.
The arithmetic deserves `exact`; the datum deserves scrutiny. Collapsing the
two in either direction is a lie:

  - calling a currency conversion `exact` launders the rate into mathematics
  - calling it `estimated` slanders arithmetic that is, in fact, exact

The subsystem introduces one status class, and only one:

    exact-given  — exact rational arithmetic, CONDITIONAL on a declared datum
                   that is carried in the result and is NOT verified by JACKAL.

`given` is a required, structured field on every such result. A datum with no
source and no as-of date is refused at the door. That is the whole point: the
tool makes declaring provenance the only way to get an answer at all.

`exact-given` is NOT a rung below `exact`, in the same way that `exact` and
`formal-bounded` are not rungs. It names a different shape of claim.
"""

import datetime
import decimal
import json
import re
import sys
from fractions import Fraction
from typing import Callable

# Everything this subsystem says about the world is informational. Even a formal-bounded
# enclosure of a standard deviation says nothing about whether the sample was
# collected correctly, and no conversion says anything about whether the
# quantity was measured correctly. The ceiling never rises above this.
CONSEQUENCE_CEILING = "informational"

UNIVERSAL_NON_CLAIMS = [
    "The JACKAL measurement orchestrator is identity-pinned but remains outside the Lean certificate chain",
    "The measurement orchestrator performs no arithmetic of its own: every arithmetic result here was produced by a delegated JACKAL runtime call recorded in `delegated_to`; library metadata such as calendar ordinals, collection counts, and lexical offsets is not an arithmetic claim",
    "The epistemic class above is the STRONGEST claim this result supports",
]


class Refusal(Exception):
    """A named refusal. Carried to the client as a result, never as an error.

    A refusal is an answer. Raising it through the JSON-RPC error channel would
    invite the client to treat it as a transport failure and retry, and retrying
    a refusal on a weaker lane until something answers is precisely the move the
    kernel's discipline forbids.
    """

    def __init__(self, reason: str, detail: str, non_claims: list[str] | None = None):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
        self.non_claims = non_claims or []


# Set only for the duration of one serialized call by ``dispatch_integrated``.
# There is intentionally no child-process fallback in this module.
JACKAL: object | None = None
_ACTIVE_IDENTITY: str | None = None


def _active_identity() -> str:
    if _ACTIVE_IDENTITY is None:
        raise RuntimeError("measurement identity is unavailable outside integrated dispatch")
    return _ACTIVE_IDENTITY

# Every delegated call made while serving one request, echoed into the result so
# a reader can confirm the measurement orchestrator computed nothing. Request handling is serialized
# by the single-threaded stdio loop, so a module-level list is safe here.
_TRACE: list[dict] = []


def exact(expression: str) -> Fraction:
    """Delegate one exact-rational computation and record the call."""
    if JACKAL is None:
        raise Refusal(
            "kernel-unavailable",
            "the measurement module is not attached to the JACKAL runtime",
        )
    out = JACKAL.call("jackal_exact", {"expression": expression})
    fields = out.get("fields", {})
    value = fields.get("exact")
    if not isinstance(value, str):
        raise Refusal("kernel-error", "jackal_exact returned no exact field")
    _TRACE.append({
        "tool": "jackal_exact",
        "parsed": fields.get("parsed", expression),
        "exact": value,
        "approx": fields.get("approx"),
        "status": out.get("status", "unknown"),
    })
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise Refusal("kernel-error", f"unparseable exact value {value!r}") from exc


def sqrt_bound(value: Fraction) -> tuple[Fraction, Fraction]:
    """Delegate a formal-bounded sqrt enclosure at a point.

    A point interval (lo == hi) is the degenerate case the certified range
    checker already handles, so a scalar square root gets the SAME Lean-checked
    treatment as an interval one. Nothing here approximates.
    """
    if value < 0:
        raise Refusal("domain", f"sqrt of a negative rational {value} is not real")
    if JACKAL is None:
        raise Refusal(
            "kernel-unavailable",
            "the measurement module is not attached to the JACKAL runtime",
        )
    arg = frac_str(value)
    out = JACKAL.call("jackal_sqrt_rat_bound", {
        "expression": "sqrt(x)", "input_lo": arg, "input_hi": arg,
    })
    text = out.get("checker_output", "")
    match = re.search(r"output\s+(\S+)\s+(\S+)\s*$", text.strip())
    if not match:
        raise Refusal("kernel-error", "could not read the enclosure from the checker output")
    lo, hi = Fraction(match.group(1)), Fraction(match.group(2))
    _TRACE.append({
        "tool": "jackal_sqrt_rat_bound",
        "parsed": f"sqrt(x) on [{arg},{arg}]",
        "enclosure": [str(lo), str(hi)],
        "status": out.get("status", "unknown"),
        "checker_rerun": out.get("checker_rerun"),
    })
    return lo, hi


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def envelope(
    *,
    status: str,
    lane: str,
    assurance: str,
    parsed: str,
    fields: dict,
    non_claims: list[str],
    given: dict | None = None,
    formal: bool = False,
) -> dict:
    """Build one JACKAL measurement result in the kernel's idiom.

    `parsed` is mandatory and never omitted, including for trivial input. The
    dominant failure at the model/tool boundary is transcription, not
    computation, so the echo is worth more than it costs on every single call.
    """
    body = {
        "status": status,
        "lane": lane,
        "assurance": assurance,
        "formal": formal,
        "consequence_ceiling": CONSEQUENCE_CEILING,
        "parsed": parsed,
        "fields": fields,
        "delegated_to": list(_TRACE),
        "non_claims": non_claims + UNIVERSAL_NON_CLAIMS,
        "identities": {"jackal_measurement_sha256": _active_identity()},
    }
    if JACKAL is not None and JACKAL.evaluator_sha256:
        body["identities"]["jackal_evaluator_sha256"] = JACKAL.evaluator_sha256
    if given is not None:
        body["given"] = given
    return body


def refusal_body(reason: str, detail: str, non_claims: list[str] | None = None) -> dict:
    return {
        "status": "refused",
        "reason": reason,
        "detail": detail,
        "consequence_ceiling": CONSEQUENCE_CEILING,
        "non_claims": (non_claims or []) + [
            "A refusal is an answer: report it as one",
            "Do NOT substitute unverified arithmetic for a refused result",
            "Do NOT retry this question on a weaker lane to obtain some number",
        ],
        "identities": {"jackal_measurement_sha256": _active_identity()},
    }


def as_fraction(text: str, subject: str) -> Fraction:
    """Parse a user-supplied number WITHOUT arithmetic.

    Literal parsing is transcription, not computation, so it happens here. The
    moment two of these meet an operator, the expression goes to the kernel.
    """
    if not isinstance(text, str) or not text.strip():
        raise Refusal("args", f"{subject} must be a non-empty string")
    raw = text.strip().replace("_", "")
    # Thousands separators are a transcription hazard, not a notation the measurement subsystem
    # guesses at: 1,234 is one number in one locale and two in another.
    if "," in raw:
        raise Refusal(
            "ambiguous-literal",
            f"{subject} contains a comma ({text!r}); comma grouping and comma decimals are "
            "indistinguishable here. Supply an unambiguous literal such as '1234' or '1234.5'.",
        )
    try:
        if "/" in raw:
            return Fraction(raw)
        return Fraction(decimal.Decimal(raw))
    except (ValueError, ArithmeticError, decimal.InvalidOperation) as exc:
        raise Refusal("args", f"{subject} is not an integer, decimal, or rational: {text!r}") from exc


def frac_str(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def approx(value: Fraction, places: int = 12) -> str:
    """Return JACKAL's decimal rendering for reading only.

    The ``places`` parameter remains for source compatibility but does not ask
    Python to round or divide. JACKAL owns the rendering as well as the exact
    rational. Reuse a matching delegated result when one exists; otherwise
    delegate an identity expression and record it in the trace.
    """
    del places
    wanted = frac_str(value)
    for item in reversed(_TRACE):
        if item.get("tool") == "jackal_exact" and item.get("exact") == wanted:
            rendered = item.get("approx")
            if isinstance(rendered, str) and rendered:
                return rendered
    exact(wanted)
    rendered = _TRACE[-1].get("approx") if _TRACE else None
    if not isinstance(rendered, str) or not rendered:
        raise Refusal("kernel-error", "jackal_exact returned no decimal rendering")
    return rendered


# ---------------------------------------------------------------------------
# Definitional unit table
#
# ONLY exact-by-definition conversions appear here. Each factor is a rational
# converting the unit to its dimension's base, alongside the instrument that
# makes it exact. A unit whose factor is empirical, drifting, or transcendental
# is absent ON PURPOSE, and absence produces a refusal rather than a guess.
#
# The notable absences, each a real laundering site:
#   - `year` / `month`  : no exact second count. `julian_year` is exact and named.
#   - `degree`/`radian` : the factor is pi/180, outside the exact-rational fragment.
#   - `tonne-of-TNT`, `calorie (nutritional)` : convention-dependent.
# ---------------------------------------------------------------------------

SI = "SI base/derived definition (BIPM SI Brochure, 9th ed.)"
YARD_POUND = "International yard and pound agreement (1959), exact by definition"
IEC = "IEC 80000-13 binary prefixes, exact by definition"

UNITS: dict[str, dict[str, tuple[str, str]]] = {
    "length": {  # base: metre
        "m": ("1", SI), "metre": ("1", SI), "meter": ("1", SI),
        "km": ("1000", SI), "cm": ("1/100", SI), "mm": ("1/1000", SI),
        "um": ("1/1000000", SI), "nm": ("1/1000000000", SI),
        "in": ("0.0254", YARD_POUND), "inch": ("0.0254", YARD_POUND),
        "ft": ("0.3048", YARD_POUND), "foot": ("0.3048", YARD_POUND),
        "yd": ("0.9144", YARD_POUND), "yard": ("0.9144", YARD_POUND),
        "mi": ("1609.344", YARD_POUND), "mile": ("1609.344", YARD_POUND),
        "nmi": ("1852", "Exact by definition (BIPM/IHO international nautical mile)"),
    },
    "mass": {  # base: kilogram
        "kg": ("1", SI), "g": ("1/1000", SI), "mg": ("1/1000000", SI),
        "t": ("1000", SI), "tonne": ("1000", SI),
        "lb": ("0.45359237", YARD_POUND), "pound": ("0.45359237", YARD_POUND),
        "oz": ("0.45359237/16", YARD_POUND),
        "st": ("0.45359237*14", YARD_POUND), "stone": ("0.45359237*14", YARD_POUND),
        "short_ton": ("0.45359237*2000", YARD_POUND),
        "long_ton": ("0.45359237*2240", YARD_POUND),
    },
    "time": {  # base: second
        "s": ("1", SI), "sec": ("1", SI), "second": ("1", SI),
        "ms": ("1/1000", SI), "us": ("1/1000000", SI), "ns": ("1/1000000000", SI),
        "min": ("60", SI), "minute": ("60", SI),
        "h": ("3600", SI), "hr": ("3600", SI), "hour": ("3600", SI),
        "day": ("86400", "Exact by definition (86400 SI seconds; NOT a solar day)"),
        "week": ("604800", "Exact by definition (7 x 86400 s)"),
        "julian_year": ("31557600", "IAU Julian year, exact by definition (365.25 x 86400 s)"),
    },
    "volume": {  # base: litre
        "l": ("1", SI), "litre": ("1", SI), "liter": ("1", SI),
        "ml": ("1/1000", SI), "m3": ("1000", SI),
        "us_gal": ("3.785411784", "US gallon = 231 cubic inches exactly (yard-and-pound)"),
        "us_qt": ("3.785411784/4", "US quart = 1/4 US gallon exactly"),
        "us_pt": ("3.785411784/8", "US pint = 1/8 US gallon exactly"),
        "us_floz": ("3.785411784/128", "US fluid ounce = 1/128 US gallon exactly"),
        "imp_gal": ("4.54609", "Imperial gallon, exact by definition (UK Weights and Measures Act 1985)"),
        "imp_pt": ("4.54609/8", "Imperial pint = 1/8 imperial gallon exactly"),
        "imp_floz": ("4.54609/160", "Imperial fluid ounce = 1/160 imperial gallon exactly"),
    },
    "speed": {  # base: metre per second
        "m/s": ("1", SI),
        "km/h": ("1000/3600", SI),
        "mph": ("1609.344/3600", YARD_POUND),
        "kn": ("1852/3600", "Knot = one nautical mile per hour, exact by definition"),
        "knot": ("1852/3600", "Knot = one nautical mile per hour, exact by definition"),
    },
    "energy": {  # base: joule
        "j": ("1", SI), "joule": ("1", SI), "kj": ("1000", SI), "mj": ("1000000", SI),
        "wh": ("3600", SI), "kwh": ("3600000", SI), "mwh": ("3600000000", SI),
        "cal": ("4.184", "Thermochemical calorie, exact by definition"),
        "kcal": ("4184", "Thermochemical kilocalorie, exact by definition"),
        "btu": ("1055.05585262", "BTU (International Table), exact by definition"),
        "ev": ("1.602176634*10^-19", "SI 2019 redefinition: elementary charge is exact"),
    },
    "power": {  # base: watt
        "w": ("1", SI), "watt": ("1", SI), "kw": ("1000", SI), "mw": ("1000000", SI),
        "hp": ("550*0.3048*0.45359237*9.80665",
               "Mechanical horsepower = 550 ft.lbf/s, exact via the defined standard gravity 9.80665 m/s^2"),
    },
    "data": {  # base: byte -- the single most productive laundering site in computing
        "b": ("1", IEC), "byte": ("1", IEC), "bit": ("1/8", IEC),
        "kb": ("1000", "SI decimal prefix: kB = 10^3 bytes"),
        "mb": ("1000000", "SI decimal prefix: MB = 10^6 bytes"),
        "gb": ("1000000000", "SI decimal prefix: GB = 10^9 bytes"),
        "tb": ("1000000000000", "SI decimal prefix: TB = 10^12 bytes"),
        "kib": ("1024", IEC), "mib": ("1048576", IEC),
        "gib": ("1073741824", IEC), "tib": ("1099511627776", IEC),
    },
}

# Units whose absence is deliberate, with the reason stated at the point of
# refusal. Guessing here would be the exact failure this subsystem exists to prevent.
REFUSED_UNITS = {
    "year": "a calendar year has no exact second count (365 or 366 days); use `julian_year` for the exact IAU definition, or jackal_date_delta for civil dates",
    "yr": "a calendar year has no exact second count; use `julian_year` or jackal_date_delta",
    "month": "a calendar month has no fixed length (28-31 days); use jackal_date_delta on real dates",
    "deg": "degree-to-radian requires pi, which is outside the exact-rational fragment",
    "degree": "degree-to-radian requires pi, which is outside the exact-rational fragment",
    "rad": "radian-to-degree requires pi, which is outside the exact-rational fragment",
    "radian": "radian-to-degree requires pi, which is outside the exact-rational fragment",
}

TEMPERATURE = {"c", "celsius", "f", "fahrenheit", "k", "kelvin", "r", "rankine"}


def find_unit(name: str) -> tuple[str, str, str]:
    """Resolve a unit to (dimension, factor-expression, authority) or refuse."""
    key = name.strip().lower().replace("^", "").replace(" ", "")
    if key in REFUSED_UNITS:
        raise Refusal("undefined-unit", f"unit {name!r} is deliberately absent: {REFUSED_UNITS[key]}")
    for dimension, table in UNITS.items():
        if key in table:
            factor, authority = table[key]
            return dimension, factor, authority
    if key in TEMPERATURE:
        return "temperature", "", "affine scale; handled separately"
    known = sorted({u for table in UNITS.values() for u in table} | TEMPERATURE)
    raise Refusal(
        "undefined-unit",
        f"unit {name!r} is not in the definitional table, and JACKAL does not guess conversion "
        f"factors. Known units: {', '.join(known)}",
    )


# ---------------------------------------------------------------------------
# jackal_convert -- definitional unit conversion
# ---------------------------------------------------------------------------

_TEMP_TO_K = {
    "c": "({v}) + 273.15", "celsius": "({v}) + 273.15",
    "f": "(({v}) - 32) * 5/9 + 273.15", "fahrenheit": "(({v}) - 32) * 5/9 + 273.15",
    "k": "({v})", "kelvin": "({v})",
    "r": "({v}) * 5/9", "rankine": "({v}) * 5/9",
}
_K_TO_TEMP = {
    "c": "({v}) - 273.15", "celsius": "({v}) - 273.15",
    "f": "(({v}) - 273.15) * 9/5 + 32", "fahrenheit": "(({v}) - 273.15) * 9/5 + 32",
    "k": "({v})", "kelvin": "({v})",
    "r": "({v}) * 9/5", "rankine": "({v}) * 9/5",
}


def tool_convert(args: dict) -> dict:
    value_text = args.get("value")
    frm = args.get("from_unit")
    to = args.get("to_unit")
    for name, val in (("value", value_text), ("from_unit", frm), ("to_unit", to)):
        if not isinstance(val, str) or not val.strip():
            raise Refusal("args", f"{name} is required and must be a non-empty string")
    value = as_fraction(value_text, "value")
    from_dim, from_factor, from_auth = find_unit(frm)
    to_dim, to_factor, to_auth = find_unit(to)
    if from_dim != to_dim:
        raise Refusal(
            "dimension-mismatch",
            f"cannot convert {frm!r} ({from_dim}) to {to!r} ({to_dim}); these are different "
            "physical dimensions and no conversion between them exists without a declared "
            "physical relation the JACKAL measurement subsystem was not given",
        )

    if from_dim == "temperature":
        # Affine scales: a temperature is a point, not a magnitude, so the
        # zero offsets do not cancel and a plain ratio would be wrong.
        kelvin = exact(_TEMP_TO_K[frm.strip().lower()].format(v=frac_str(value)))
        result = exact(_K_TO_TEMP[to.strip().lower()].format(v=frac_str(kelvin)))
        auth = "Exact by definition (ITS-90 fixed offsets 273.15 and 459.67; scale factors 9/5)"
        note = ("temperature is an AFFINE scale: this converts a POINT on the scale. "
                "A temperature DIFFERENCE converts differently (offsets cancel).")
    else:
        result = exact(f"({frac_str(value)}) * ({from_factor}) / ({to_factor})")
        auth = f"from: {from_auth} | to: {to_auth}"
        note = None

    fields = {
        "exact": frac_str(result),
        "approx": approx(result),
        "from": frm, "to": to, "dimension": from_dim,
        "definition_authority": auth,
    }
    if note:
        fields["scale_note"] = note
    non_claims = [
        "This converts a NUMBER between units defined to be exactly related; it does not verify that the input quantity was measured correctly",
        "Only definitional (exact-by-definition) conversions are in the table; empirical or convention-dependent factors are absent and refuse",
    ]
    if note:
        non_claims.insert(0, "This is a SCALE POINT conversion, NOT a temperature difference")
    return envelope(
        status="exact", lane="jackal-measure-convert",
        assurance="exact rational conversion between definitionally-related units (not checker-covered)",
        parsed=f"{frac_str(value)} {frm} -> {to}",
        fields=fields, non_claims=non_claims,
    )


# ---------------------------------------------------------------------------
# jackal_rate_apply -- the exact-given lane
# ---------------------------------------------------------------------------

def tool_rate_apply(args: dict) -> dict:
    """Apply a declared rate. The arithmetic is exact; the RATE is not mathematics.

    Every argument below is required, and that is the entire design. A rate with
    no source and no as-of date is a number of unknown origin, and multiplying
    by it silently promotes that unknown origin to the authority of the result.
    Refusing at the door is what makes the provenance impossible to skip.
    """
    value_text = args.get("value")
    rate_text = args.get("rate")
    source = args.get("rate_source")
    asof = args.get("rate_asof")
    frm = args.get("from_label") or "from"
    to = args.get("to_label") or "to"

    missing = [n for n, v in (("value", value_text), ("rate", rate_text),
                              ("rate_source", source), ("rate_asof", asof))
               if not isinstance(v, str) or not v.strip()]
    if missing:
        raise Refusal(
            "undeclared-datum",
            f"missing required declaration(s): {', '.join(missing)}. A rate is a DATUM, not "
            "mathematics: JACKAL will not apply one that does not carry its source and as-of "
            "date, because the result would inherit an authority the rate never had.",
        )
    value = as_fraction(value_text, "value")
    rate = as_fraction(rate_text, "rate")
    if rate <= 0:
        raise Refusal("args", f"rate must be positive; got {rate_text!r}")
    result = exact(f"({frac_str(value)}) * ({frac_str(rate)})")
    return envelope(
        status="exact-given", lane="jackal-measure-rate",
        assurance="exact rational arithmetic CONDITIONAL on the declared rate below; the rate itself is unverified",
        parsed=f"{frac_str(value)} {frm} x {frac_str(rate)} -> {to}",
        given={
            "datum": "conversion rate",
            "rate": frac_str(rate),
            "rate_approx": approx(rate),
            "direction": f"1 {frm} = {frac_str(rate)} {to}",
            "source": source.strip(),
            "as_of": asof.strip(),
        },
        fields={"exact": frac_str(result), "approx": approx(result),
                "from_label": frm, "to_label": to},
        non_claims=[
            "JACKAL did NOT verify the rate, its source, or its as-of date; all three are reported as supplied",
            "This result is exact ONLY under the declared rate; a different rate yields a different exact result",
            "`exact-given` is NOT a weaker `exact`: the arithmetic is exact and the datum is unverified. Do not report it as `exact`, and do not soften it to `estimated`",
            "Rates change: an as-of date in the past does not describe the present",
        ],
    )


# ---------------------------------------------------------------------------
# jackal_percent
# ---------------------------------------------------------------------------

def tool_percent(args: dict) -> dict:
    op = (args.get("op") or "").strip().lower()
    a_text, b_text = args.get("a"), args.get("b")
    if not isinstance(a_text, str) or not isinstance(b_text, str):
        raise Refusal("args", "both `a` and `b` are required strings")
    a, b = as_fraction(a_text, "a"), as_fraction(b_text, "b")

    ops = {
        "of": ("({a}) * ({b}) / 100", "a% of b", "value"),
        "change": ("(({b}) - ({a})) * 100 / ({a})", "percent change from a to b", "percent"),
        "ratio": ("({a}) * 100 / ({b})", "a as a percentage of b", "percent"),
        "points": ("({b}) - ({a})", "difference in PERCENTAGE POINTS between a% and b%", "percentage_points"),
        "increase": ("({a}) * (1 + ({b})/100)", "a increased by b%", "value"),
        "decrease": ("({a}) * (1 - ({b})/100)", "a decreased by b%", "value"),
    }
    if op not in ops:
        raise Refusal("args", f"op must be one of {', '.join(sorted(ops))}; got {op!r}")
    if op in ("change", "ratio") and (a if op == "change" else b) == 0:
        raise Refusal("domain", f"op {op!r} divides by zero for the given inputs")

    template, meaning, unit = ops[op]
    result = exact(template.format(a=frac_str(a), b=frac_str(b)))
    non_claims = [
        "A percentage is meaningless without its base; the base used here is exactly as supplied",
    ]
    if op in ("change", "ratio", "points"):
        non_claims.insert(0,
            "PERCENT vs PERCENTAGE POINTS are different quantities and are routinely conflated: "
            "`change`/`ratio` return PERCENT (relative), `points` returns PERCENTAGE POINTS (absolute). "
            f"This result is in {unit.upper()}.")
    if op == "change":
        non_claims.append(
            "Percent change is asymmetric: a rise of x% followed by a fall of x% does not return to the start")
    return envelope(
        status="exact", lane="jackal-measure-percent",
        assurance="exact rational arithmetic (not checker-covered)",
        parsed=f"{op}(a={frac_str(a)}, b={frac_str(b)}) = {meaning}",
        fields={"exact": frac_str(result), "approx": approx(result),
                "result_unit": unit, "meaning": meaning},
        non_claims=non_claims,
    )


# ---------------------------------------------------------------------------
# jackal_date_delta -- civil-date arithmetic
# ---------------------------------------------------------------------------

CALENDAR = "proleptic Gregorian"


def _civil_date(text: str, subject: str) -> datetime.date:
    if not isinstance(text, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text.strip()):
        raise Refusal(
            "args",
            f"{subject} must be an ISO civil date YYYY-MM-DD; got {text!r}. This JACKAL lane takes civil "
            "dates only: a wall-clock time carries a timezone, and a timezone is a datum "
            "(tzdata rules, DST transitions) that this lane does not accept.",
        )
    try:
        return datetime.date.fromisoformat(text.strip())
    except ValueError as exc:
        raise Refusal("args", f"{subject} is not a real calendar date: {text!r} ({exc})") from exc


def tool_date_delta(args: dict) -> dict:
    op = (args.get("op") or "").strip().lower()
    given = {
        "datum": "calendar convention",
        "calendar": CALENDAR,
        "day_length": "one civil day, NOT 86400 SI seconds",
        "excludes": "timezones, DST transitions, leap seconds",
        "source": "Python datetime.date proleptic-Gregorian calendar semantics",
        "as_of": "JACKAL measurement definition 1.1.0 (this convention is not time-varying)",
    }
    non_claims = [
        "Civil-date arithmetic ONLY: no timezone, no DST, no leap seconds, no wall-clock times",
        "A civil day is not a fixed number of seconds; do not convert this result to seconds by multiplying by 86400 unless that assumption is stated",
        f"Dates before the 1582 Gregorian adoption are interpreted {CALENDAR}ly and will NOT match historical Julian records",
        "`exact-given` is NOT a weaker `exact`: the day count is exact under the declared calendar convention",
    ]

    if op == "diff":
        start = _civil_date(args.get("start"), "start")
        end = _civil_date(args.get("end"), "end")
        # The calendar->ordinal mapping is library calendar logic, not arithmetic;
        # the SUBTRACTION is what goes to the kernel.
        days = exact(f"{end.toordinal()} - {start.toordinal()}")
        fields = {
            "exact_days": frac_str(days),
            "start": start.isoformat(), "end": end.isoformat(),
            "start_ordinal": str(start.toordinal()), "end_ordinal": str(end.toordinal()),
            "direction": "end - start (negative means end precedes start)",
        }
        parsed = f"diff({start.isoformat()} -> {end.isoformat()})"
    elif op == "add":
        start = _civil_date(args.get("start"), "start")
        days_text = args.get("days")
        offset = as_fraction(days_text, "days")
        if offset.denominator != 1:
            raise Refusal("args", f"days must be a whole number of civil days; got {days_text!r}")
        target_ordinal = exact(f"{start.toordinal()} + ({frac_str(offset)})")
        n = int(target_ordinal)
        if not 1 <= n <= datetime.date.max.toordinal():
            raise Refusal("domain", f"resulting date falls outside the representable calendar range (ordinal {n})")
        result = datetime.date.fromordinal(n)
        fields = {
            "result": result.isoformat(), "start": start.isoformat(),
            "days_added": frac_str(offset), "result_ordinal": str(n),
        }
        parsed = f"add({start.isoformat()} + {frac_str(offset)} days)"
    else:
        raise Refusal("args", f"op must be 'diff' or 'add'; got {op!r}")

    return envelope(
        status="exact-given", lane="jackal-measure-date",
        assurance="exact day arithmetic CONDITIONAL on the declared calendar convention below",
        parsed=parsed, given=given, fields=fields, non_claims=non_claims,
    )


# ---------------------------------------------------------------------------
# jackal_stat -- descriptive statistics, honestly classed
# ---------------------------------------------------------------------------

def tool_stat(args: dict) -> dict:
    sample = args.get("sample")
    if isinstance(sample, str):
        parts = [p for p in re.split(r"[\s;]+", sample.strip()) if p]
    elif isinstance(sample, list):
        parts = [str(p) for p in sample]
    else:
        raise Refusal("args", "sample must be a whitespace-separated string or a list of numbers")
    if not parts:
        raise Refusal("args", "sample is empty")
    values = [as_fraction(p, f"sample[{i}]") for i, p in enumerate(parts)]
    n = len(values)

    total = exact(" + ".join(f"({frac_str(v)})" for v in values))
    mean = exact(f"({frac_str(total)}) / {n}")
    ordered = sorted(values)
    if n % 2 == 1:
        median = ordered[n // 2]
        median_note = "middle order statistic"
    else:
        median = exact(f"(({frac_str(ordered[n//2 - 1])}) + ({frac_str(ordered[n//2])})) / 2")
        median_note = "mean of the two central order statistics"

    ss = exact(" + ".join(f"(({frac_str(v)}) - ({frac_str(mean)}))^2" for v in values))
    pop_var = exact(f"({frac_str(ss)}) / {n}")
    field_status = {k: "exact" for k in
                    ("n", "sum", "mean", "median", "min", "max", "range", "population_variance")}
    fields = {
        "n": str(n),
        "sum": frac_str(total), "mean": frac_str(mean), "mean_approx": approx(mean),
        "median": frac_str(median), "median_note": median_note,
        "min": frac_str(ordered[0]), "max": frac_str(ordered[-1]),
        "range": frac_str(exact(f"({frac_str(ordered[-1])}) - ({frac_str(ordered[0])})")),
        "population_variance": frac_str(pop_var),
    }
    if n > 1:
        sample_var = exact(f"({frac_str(ss)}) / {n - 1}")
        fields["sample_variance"] = frac_str(sample_var)
        field_status["sample_variance"] = "exact"
    else:
        fields["sample_variance"] = "undefined (n=1: division by n-1 = 0)"
        field_status["sample_variance"] = "undefined"

    non_claims = [
        "DESCRIPTIVE ONLY. These summarize the supplied numbers and nothing else",
        "NOT inferential: no population parameter, confidence interval, significance, or distributional assumption is claimed or implied",
        "The mean is not robust to outliers; the median is reported alongside it for that reason",
        "n is the count of numbers SUPPLIED, which is not evidence that the sample was drawn correctly or is representative of anything",
    ]

    if args.get("include_stddev"):
        lo, hi = sqrt_bound(pop_var)
        fields["population_stddev_enclosure"] = [frac_str(lo), frac_str(hi)]
        fields["population_stddev_approx"] = f"[{approx(lo)}, {approx(hi)}]"
        field_status["population_stddev_enclosure"] = "formal-bounded"
        non_claims.insert(0,
            "The field `population_stddev_enclosure` is FORMAL-BOUNDED (a Lean-checked ENCLOSURE), "
            "NOT exact, and NOT a single number. The top-level `exact` describes the other fields. "
            "Report it as an interval, never as a point value.")

    return envelope(
        status="exact", lane="jackal-measure-stat",
        assurance="exact rational descriptive statistics; see `field_status` for any field carrying a different class",
        parsed=f"n={n} sample=[{', '.join(frac_str(v) for v in values)}]",
        fields={**fields, "field_status": field_status},
        non_claims=non_claims,
    )


# ---------------------------------------------------------------------------
# jackal_compare -- dimension-aware comparison
# ---------------------------------------------------------------------------

BASE_UNITS = {
    "dimensionless": "one",
    "length": "m",
    "mass": "kg",
    "time": "s",
    "volume": "l",
    "speed": "m/s",
    "energy": "j",
    "power": "w",
    "data": "b",
    "temperature": "k",
}
COMPARISON_LABELS = {"usd", "eur", "gbp", "jpy"}


def _unit_key(name: str) -> str:
    return name.strip().lower().replace("^", "").replace(" ", "")


def _quantity_in_base(value_text: object, unit_text: object, subject: str) -> dict:
    """Normalize one quantity through JACKAL, returning base-unit metadata."""
    value = as_fraction(value_text, f"{subject}_value")
    if unit_text is None:
        normalized = exact(frac_str(value))
        return {
            "dimension": "dimensionless",
            "base_unit": BASE_UNITS["dimensionless"],
            "value": normalized,
            "authority": "dimensionless identity",
            "input_unit": None,
        }
    if not isinstance(unit_text, str) or not unit_text.strip():
        raise Refusal("args", f"{subject}_unit must be a non-empty string when supplied")
    label_key = _unit_key(unit_text)
    if label_key in COMPARISON_LABELS:
        normalized = exact(frac_str(value))
        label = label_key.upper()
        return {
            "dimension": f"currency:{label}",
            "base_unit": label,
            "value": normalized,
            "authority": "nominal currency-label identity; no exchange-rate relation is implied",
            "input_unit": unit_text.strip(),
        }
    dimension, factor, authority = find_unit(unit_text)
    if dimension == "temperature":
        key = _unit_key(unit_text)
        normalized = exact(_TEMP_TO_K[key].format(v=frac_str(value)))
        authority = "Exact affine scale definition; normalized to kelvin scale points"
    else:
        normalized = exact(f"({frac_str(value)}) * ({factor})")
    return {
        "dimension": dimension,
        "base_unit": BASE_UNITS[dimension],
        "value": normalized,
        "authority": authority,
        "input_unit": unit_text.strip(),
    }


def tool_compare(args: dict) -> dict:
    """Compare dimensioned magnitudes, requiring provenance across dimensions."""
    a = _quantity_in_base(args.get("a_value"), args.get("a_unit"), "a")
    b = _quantity_in_base(args.get("b_value"), args.get("b_unit"), "b")
    same_dimension = a["dimension"] == b["dimension"]
    supplied_rate = args.get("rate")
    given = None

    if same_dimension:
        if any(args.get(key) not in (None, "") for key in ("rate", "rate_source", "rate_asof")):
            raise Refusal(
                "args",
                "a declared rate is only accepted when the dimensions differ; same-dimension "
                "quantities are compared through their exact definitional base-unit conversions",
            )
        a_comparable = a["value"]
        b_comparable = b["value"]
        base_unit = a["base_unit"]
        status = "exact"
        assurance = "exact rational comparison after definitional base-unit normalization (not checker-covered)"
    else:
        if supplied_rate is None:
            raise Refusal(
                "dimension-mismatch-no-rate",
                f"cannot compare {a['dimension']} with {b['dimension']} without a declared rate. "
                f"Supply `rate`, `rate_source`, and `rate_asof`, where 1 {a['base_unit']} "
                f"of a is declared equal to `rate` {b['base_unit']} of b.",
            )
        if not isinstance(supplied_rate, str) or not supplied_rate.strip():
            raise Refusal("args", "rate must be a non-empty numeric string when dimensions differ")
        source = args.get("rate_source")
        asof = args.get("rate_asof")
        missing = [
            name for name, value in (("rate_source", source), ("rate_asof", asof))
            if not isinstance(value, str) or not value.strip()
        ]
        if missing:
            raise Refusal(
                "undeclared-datum",
                f"missing required declaration(s): {', '.join(missing)}. A cross-dimension "
                "comparison rate is a DATUM, not mathematics, and must carry source and as-of.",
            )
        rate = as_fraction(supplied_rate, "rate")
        if rate <= 0:
            raise Refusal("args", f"rate must be positive; got {supplied_rate!r}")
        a_comparable = exact(f"({frac_str(a['value'])}) * ({frac_str(rate)})")
        b_comparable = b["value"]
        base_unit = b["base_unit"]
        status = "exact-given"
        assurance = (
            "exact rational comparison CONDITIONAL on the declared cross-dimension rate; "
            "the rate itself is unverified"
        )
        given = {
            "datum": "cross-dimension comparison rate",
            "rate": frac_str(rate),
            "rate_approx": approx(rate),
            "direction": f"1 {a['base_unit']} ({a['dimension']}) = {frac_str(rate)} "
                         f"{b['base_unit']} ({b['dimension']})",
            "source": source.strip(),
            "as_of": asof.strip(),
        }

    difference = exact(f"({frac_str(a_comparable)}) - ({frac_str(b_comparable)})")
    if a_comparable > b_comparable:
        verdict = "a_greater"
    elif b_comparable > a_comparable:
        verdict = "b_greater"
    else:
        verdict = "equal"

    fields = {
        "verdict": verdict,
        "difference": frac_str(difference),
        "base_unit": base_unit,
        "a_in_base": frac_str(a_comparable),
        "b_in_base": frac_str(b_comparable),
        "a_dimension": a["dimension"],
        "b_dimension": b["dimension"],
        "definition_authority": {"a": a["authority"], "b": b["authority"]},
    }
    if not same_dimension:
        fields["a_before_declared_rate"] = frac_str(a["value"])
        fields["a_original_base_unit"] = a["base_unit"]
    if b_comparable != 0:
        fields["ratio"] = frac_str(
            exact(f"({frac_str(a_comparable)}) / ({frac_str(b_comparable)})")
        )

    parsed = (
        f"compare(a={frac_str(a['value'])} {a['base_unit']}[{a['dimension']}], "
        f"b={frac_str(b['value'])} {b['base_unit']}[{b['dimension']}])"
    )
    if given is not None:
        parsed += f" under ({given['direction']})"
    non_claims = [
        "A comparison of magnitudes is not a comparison of value, quality, or suitability",
        "Equal magnitudes in different units are not the same quantity",
    ]
    if given is not None:
        non_claims.extend([
            "The verdict may reverse under a different declared rate; state the rate whenever reporting the verdict",
            "JACKAL did NOT verify the rate, its source, or its as-of date; all are reported as supplied",
            "`exact-given` is NOT a weaker `exact`: the arithmetic is exact and the datum is unverified. Do not report it as `exact`, and do not soften it to `estimated`",
        ])
    if a["dimension"] == "temperature" or b["dimension"] == "temperature":
        non_claims.insert(0, "Temperature inputs are SCALE POINTS normalized to kelvin, NOT temperature differences")
    return envelope(
        status=status,
        lane="jackal-measure-compare",
        assurance=assurance,
        parsed=parsed,
        fields=fields,
        given=given,
        non_claims=non_claims,
    )


# ---------------------------------------------------------------------------
# jackal_scan -- lexical noticing prosthetic
# ---------------------------------------------------------------------------

DERIVATION_CUES = (
    "total", "sum", "combined", "difference", "average", "mean", "median",
    "per", "each", "times", "twice", "half", "double", "increase", "decrease",
    "up from", "down from", "faster", "slower", "cheaper", "more than", "less than",
    "about", "roughly", "approximately", "estimated",
)
OBSERVATION_CUES = (
    "listed", "reported", "read", "says", "shows", "according to", "output",
    "returned", "printed", "per the",
)


def _number_pattern() -> str:
    # Keep scientific notation as one lexical token.  The ordering is
    # intentional: coefficient-times-ten, e notation, and powers of ten must
    # win before the final plain-decimal alternative can consume a prefix.
    decimal_number = r"\d[\d,]*(?:\.\d+)?"
    signed_exponent = r"[+-]?\d+"
    braced_exponent = rf"\{{{signed_exponent}\}}"
    superscript_exponent = r"[⁺⁻]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+"
    power = rf"(?:\^\s*(?:{braced_exponent}|{signed_exponent})|\*\*\s*(?:{braced_exponent}|{signed_exponent})|{superscript_exponent})"
    ten_power = rf"10\s*{power}"
    return rf"(?:{decimal_number}\s*[×·*]\s*{ten_power}|{decimal_number}[eE]{signed_exponent}|{ten_power}|{decimal_number})"


def _scan_patterns() -> list[tuple[str, re.Pattern]]:
    known_units = {unit for table in UNITS.values() for unit in table}
    known_units.update(TEMPERATURE)
    known_units.update(REFUSED_UNITS)
    unit_alt = "|".join(re.escape(unit) for unit in sorted(known_units, key=len, reverse=True))
    number = _number_pattern()
    return [
        ("version", re.compile(r"(?<![\w.])(?P<num>\d+\.\d+(?:\.\d+)+)(?![\w.])")),
        ("date_iso", re.compile(r"(?<!\d)(?P<num>\d{4}-\d{2}-\d{2})(?!\d)")),
        ("currency", re.compile(rf"[$£€¥]\s?(?P<num>{number})")),
        ("currency", re.compile(rf"(?<!\w)(?P<num>{number})\s?(?:USD|EUR|GBP|JPY)\b", re.IGNORECASE)),
        ("percentage", re.compile(rf"(?<![\w.])(?P<num>{number})\s?%")),
        ("dimensioned", re.compile(rf"(?<![\w.])(?P<num>{number})\s*(?P<unit>{unit_alt})(?![\w/])", re.IGNORECASE)),
        # Sentence punctuation after a numeral is permitted; a dot/comma only
        # blocks the match when it begins another numeric component.
        ("plain", re.compile(rf"(?<![\w.])(?P<num>{number})(?!\w|[.,]\d)")),
    ]


SCAN_PATTERNS = _scan_patterns()
CURRENCY_MARKERS = re.compile(r"[$£€¥]|\b(?:USD|EUR|GBP|JPY)\b", re.IGNORECASE)


def _cue_hits(context: str) -> list[str]:
    lower = context.lower()
    hits = [cue for cue in DERIVATION_CUES if cue in lower]
    symbol_tests = (
        ("+", "+" in context),
        ("-", bool(re.search(r"(?:\d|\s)-\s*(?:\d|[$£€¥])", context))),
        ("×", "×" in context),
        ("x", bool(re.search(r"(?<!\w)x(?!\w)", lower))),
        ("/", "/" in context),
        ("%", "%" in context),
        ("~", "~" in context),
        ("≈", "≈" in context),
    )
    hits.extend(symbol for symbol, present in symbol_tests if present)
    return list(dict.fromkeys(hits))


def _observation_hits(text: str, full_start: int, full_end: int, context: str) -> list[str]:
    lower = context.lower()
    hits = [cue for cue in OBSERVATION_CUES if cue in lower]
    before = text[:full_start].rstrip()
    after = text[full_end:].lstrip()
    if before and after and (before[-1], after[0]) in {
        ('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’"),
    }:
        hits.append("quoted")
    return list(dict.fromkeys(hits))


def _currency_marker_set(text: str) -> set[str]:
    aliases = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "YEN"}
    markers = set()
    for match in CURRENCY_MARKERS.finditer(text):
        token = match.group(0)
        markers.add(aliases.get(token, token.upper()))
    return markers


def tool_scan(args: dict) -> dict:
    text = args.get("text")
    if not isinstance(text, str) or not text:
        raise Refusal("args", "text is required and must be a non-empty string")
    window = args.get("context_window", 60)
    if isinstance(window, bool) or not isinstance(window, int) or window < 0:
        raise Refusal("args", "context_window must be a non-negative integer")

    candidates = []
    for priority, (kind, pattern) in enumerate(SCAN_PATTERNS):
        for match in pattern.finditer(text):
            candidates.append({
                "priority": priority,
                "kind": kind,
                "full_start": match.start(),
                "full_end": match.end(),
                "offset": match.start("num"),
                "text": match.group("num"),
                "unit": match.groupdict().get("unit"),
            })
    candidates.sort(key=lambda item: (
        item["full_start"], item["priority"], -(item["full_end"] - item["full_start"])
    ))

    selected = []
    occupied_until = -1
    for candidate in candidates:
        if candidate["full_start"] < occupied_until:
            continue
        selected.append(candidate)
        occupied_until = candidate["full_end"]

    cross_currency = len(_currency_marker_set(text)) > 1
    findings = []
    by_kind: dict[str, int] = {}
    unrouted = []
    for candidate in selected:
        context_start = max(0, candidate["full_start"] - window)
        context_end = min(len(text), candidate["full_end"] + window)
        context = text[context_start:context_end]
        cue_context = (
            text[context_start:candidate["full_start"]]
            + " " * (candidate["full_end"] - candidate["full_start"])
            + text[candidate["full_end"]:context_end]
        )
        derived = _cue_hits(cue_context)
        observed = _observation_hits(
            text, candidate["full_start"], candidate["full_end"], cue_context
        )
        kind = candidate["kind"]
        if kind == "version":
            route = None
            must_declare = False
        elif kind == "currency" and cross_currency:
            route = "jackal_rate_apply / jackal_compare"
            must_declare = True
        elif kind == "currency":
            route = "jackal_exact" if derived else None
            must_declare = bool(derived)
        elif kind == "percentage":
            route = "jackal_percent"
            must_declare = bool(derived)
        elif kind == "dimensioned":
            route = "jackal_convert"
            must_declare = bool(derived)
        elif kind == "date_iso":
            route = "jackal_date_delta" if derived else None
            must_declare = bool(derived)
        else:
            route = "jackal_exact" if derived else None
            must_declare = bool(derived)

        finding = {
            "text": candidate["text"],
            "offset": candidate["offset"],
            "kind": kind,
            "context": context,
            "cues_derived": derived,
            "cues_observed": observed,
            "route": route,
            "must_declare": must_declare,
        }
        if candidate["unit"]:
            finding["unit"] = candidate["unit"]
        findings.append(finding)
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if must_declare:
            unrouted.append({
                "text": candidate["text"],
                "offset": candidate["offset"],
                "kind": kind,
                "route": route,
            })

    summary = {
        "total_numerals": len(findings),
        "by_kind": by_kind,
        "flagged": len(unrouted),
        "unrouted_derived": unrouted,
    }
    return envelope(
        status="checked",
        lane="jackal-measure-scan",
        assurance="checked lexical classification only; no numeral was mathematically verified",
        parsed=f"text={json.dumps(text, ensure_ascii=False)} context_window={window}",
        fields={"numerals": findings, "summary": summary},
        non_claims=[
            "This is a LEXICAL scan. It reads characters, not provenance",
            "The ABSENCE of a flag is NOT evidence that a numeral was observed rather than derived. A clean scan means nothing was detected, not that nothing is wrong",
            "Cue matching is heuristic and both over- and under-fires. Version strings, ordinals, identifiers, and quoted figures are frequently misclassified",
            "This tool cannot verify any numeral. It only suggests where one should be sent",
            "Offsets and counts are lexical metadata returned by Python string/regex operations, not JACKAL arithmetic results",
        ],
    )


# ---------------------------------------------------------------------------
# Tool registry and stdio MCP server
# ---------------------------------------------------------------------------

DRAFT7 = "http://json-schema.org/draft-07/schema#"
NUMBER_STRING = {
    "type": "string",
    "minLength": 1,
    "description": "Unambiguous integer, decimal, or rational string; commas refuse",
}
NONEMPTY_STRING = {"type": "string", "minLength": 1}


def _schema(properties: dict, required: list[str]) -> dict:
    return {
        "$schema": DRAFT7,
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TOOL_REGISTRY = {
    "jackal_convert": (
        tool_convert,
        "Convert definitionally related units through JACKAL. Returns status=exact. Refuses ambiguous literals, undefined units, deliberately excluded units, dimension mismatches, kernel loss, and kernel refusal.",
        _schema({
            "value": NUMBER_STRING,
            "from_unit": {**NONEMPTY_STRING, "description": "Source unit token from the JACKAL measurement subsystem's exact-by-definition table"},
            "to_unit": {**NONEMPTY_STRING, "description": "Target unit token in the same physical dimension"},
        }, ["value", "from_unit", "to_unit"]),
    ),
    "jackal_rate_apply": (
        tool_rate_apply,
        "Apply a caller-declared rate through JACKAL. Returns status=exact-given, never exact. Refuses unless value, positive rate, rate_source, and rate_asof are all declared; also refuses kernel loss or kernel refusal.",
        _schema({
            "value": NUMBER_STRING,
            "rate": NUMBER_STRING,
            "rate_source": {**NONEMPTY_STRING, "description": "Caller-declared provenance for the rate; the JACKAL measurement subsystem does not verify it"},
            "rate_asof": {**NONEMPTY_STRING, "description": "Caller-declared date/time or period when the rate applied"},
            "from_label": {**NONEMPTY_STRING, "description": "Optional source quantity label"},
            "to_label": {**NONEMPTY_STRING, "description": "Optional target quantity label"},
        }, ["value", "rate", "rate_source", "rate_asof"]),
    ),
    "jackal_percent": (
        tool_percent,
        "Perform percentage operations through JACKAL. Returns status=exact and distinguishes percent from percentage points. Refuses unknown operations, ambiguous literals, division by zero, kernel loss, and kernel refusal.",
        _schema({
            "op": {"type": "string", "enum": ["of", "change", "ratio", "points", "increase", "decrease"]},
            "a": NUMBER_STRING,
            "b": NUMBER_STRING,
        }, ["op", "a", "b"]),
    ),
    "jackal_date_delta": (
        tool_date_delta,
        "Compute proleptic-Gregorian civil-date differences or additions through JACKAL. Returns status=exact-given. Refuses wall-clock timestamps, invalid dates, fractional day offsets, range overflow, kernel loss, and kernel refusal.",
        _schema({
            "op": {"type": "string", "enum": ["diff", "add"]},
            "start": {**NONEMPTY_STRING, "description": "ISO civil date YYYY-MM-DD"},
            "end": {**NONEMPTY_STRING, "description": "ISO civil date YYYY-MM-DD; required for diff"},
            "days": {**NUMBER_STRING, "description": "Whole civil-day offset; required for add"},
        }, ["op", "start"]),
    ),
    "jackal_stat": (
        tool_stat,
        "Compute descriptive statistics through JACKAL. Top-level status=exact; requested population_stddev_enclosure is separately status=formal-bounded. Refuses empty/malformed samples, ambiguous literals, kernel loss, and kernel refusal.",
        _schema({
            "sample": {
                "description": "Whitespace/semicolon-separated numeric string or an array of numeric strings/integers; JSON floats refuse to avoid binary-float transcription",
                "anyOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": ["string", "integer"]}},
                ],
            },
            "include_stddev": {"type": "boolean", "default": False},
        }, ["sample"]),
    ),
    "jackal_compare": (
        tool_compare,
        "Compare dimensioned magnitudes through JACKAL. Returns status=exact for dimensionless or same-dimension comparisons and status=exact-given across dimensions. Refuses cross-dimension comparison without a positive rate plus source and as-of, undefined units, kernel loss, and kernel refusal.",
        _schema({
            "a_value": NUMBER_STRING,
            "a_unit": {**NONEMPTY_STRING, "description": "Optional unit; omit for dimensionless a"},
            "b_value": NUMBER_STRING,
            "b_unit": {**NONEMPTY_STRING, "description": "Optional unit; omit for dimensionless b"},
            "rate": {**NUMBER_STRING, "description": "Required only across dimensions: 1 a-base-unit equals rate b-base-units"},
            "rate_source": {**NONEMPTY_STRING, "description": "Required provenance whenever rate is supplied"},
            "rate_asof": {**NONEMPTY_STRING, "description": "Required as-of declaration whenever rate is supplied"},
        }, ["a_value", "b_value"]),
    ),
    "jackal_scan": (
        tool_scan,
        "Lexically audit draft prose for numerals and suggest routing lanes. Returns status=checked and computes/verifies no mathematical result. Refuses missing text or an invalid context window; a clean scan is never evidence of sound provenance.",
        _schema({
            "text": {"type": "string", "minLength": 1, "description": "Draft prose to audit before sending"},
            "context_window": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 60},
        }, ["text"]),
    ),
}

TOOL_TITLES = {
    "jackal_convert": "Convert Definitional Units",
    "jackal_rate_apply": "Apply a Declared Rate",
    "jackal_percent": "Compute Percentage Operations",
    "jackal_date_delta": "Compute Civil-Date Delta",
    "jackal_stat": "Compute Descriptive Statistics",
    "jackal_compare": "Compare Dimensioned Quantities",
    "jackal_scan": "Scan Draft Numerals",
}
TOOL_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


def _tool_definitions() -> list[dict]:
    return [
        {
            "name": name,
            "title": TOOL_TITLES[name],
            "description": description,
            "inputSchema": schema,
            "annotations": dict(TOOL_ANNOTATIONS),
        }
        for name, (_handler, description, schema) in TOOL_REGISTRY.items()
    ]


def _matches_schema(value: object, schema: dict) -> bool:
    if "anyOf" in schema:
        return any(_matches_schema(value, branch) for branch in schema["anyOf"])
    expected = schema.get("type")
    if isinstance(expected, list):
        return any(_matches_schema(value, {**schema, "type": item}) for item in expected)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "array":
        if not isinstance(value, list):
            return False
        item_schema = schema.get("items")
        return item_schema is None or all(_matches_schema(item, item_schema) for item in value)
    if expected == "object":
        return isinstance(value, dict)
    return True


def _validate_arguments(tool_name: str, arguments: object) -> dict:
    if not isinstance(arguments, dict):
        raise Refusal("args", "tool arguments must be a JSON object")
    schema = TOOL_REGISTRY[tool_name][2]
    properties = schema["properties"]
    extras = sorted(set(arguments) - set(properties))
    if extras:
        raise Refusal("args", f"unexpected argument(s): {', '.join(extras)}")
    for name, value in arguments.items():
        property_schema = properties[name]
        if not _matches_schema(value, property_schema):
            raise Refusal("args", f"argument {name!r} does not match its declared JSON type")
        enum = property_schema.get("enum")
        if enum is not None and value not in enum:
            raise Refusal("args", f"argument {name!r} must be one of {', '.join(enum)}")
        if isinstance(value, str) and property_schema.get("minLength", 0) > 0 and not value:
            raise Refusal("args", f"argument {name!r} must not be empty")
        if isinstance(value, int) and not isinstance(value, bool):
            if "minimum" in property_schema and value < property_schema["minimum"]:
                raise Refusal("args", f"argument {name!r} is below its minimum")
            if "maximum" in property_schema and value > property_schema["maximum"]:
                raise Refusal("args", f"argument {name!r} exceeds its maximum")
    return arguments


MEASUREMENT_TOOL_NAMES = frozenset(TOOL_REGISTRY)


def tool_definitions() -> list[dict]:
    """Return fresh MCP definitions for the identity-pinned wrapper to merge."""
    return _tool_definitions()


class _IntegratedKernelBridge:
    """Synchronous facade over the wrapper's serialized runtime callback."""

    def __init__(self, callback: Callable[[str, dict], dict]) -> None:
        self._callback = callback
        self._evaluator_sha: str | None = None

    def call(self, tool: str, arguments: dict) -> dict:
        out = self._callback(tool, arguments)
        if not isinstance(out, dict):
            raise Refusal("kernel-error", f"{tool} returned no structured content")
        if out.get("status") == "refused":
            raise Refusal(
                f"kernel-refused:{out.get('reason', 'unnamed')}",
                f"JACKAL {tool} refused: {out.get('detail', '(no detail)')}",
                ["The underlying kernel refused; no measurement-side arithmetic was substituted"],
            )
        ident = out.get("identities")
        if isinstance(ident, dict) and isinstance(ident.get("evaluator_sha256"), str):
            self._evaluator_sha = ident["evaluator_sha256"]
        return out

    @property
    def evaluator_sha256(self) -> str | None:
        return self._evaluator_sha


def dispatch_integrated(
    tool_name: str,
    arguments: object,
    kernel_call: Callable[[str, dict], dict],
    identity_sha256: str,
) -> dict:
    """Run one measurement tool through the caller-supplied JACKAL backend.

    Runtime transport and cancellation exceptions intentionally propagate to
    the wrapper, which already maps them to MCP errors and reaps the process
    group.  Only epistemic/argument refusals become ordinary JACKAL refusal
    payloads here.
    """
    if re.fullmatch(r"[0-9a-f]{64}", identity_sha256) is None:
        raise RuntimeError("measurement module identity is invalid")
    if tool_name not in TOOL_REGISTRY:
        raise RuntimeError("unknown integrated measurement tool")

    global JACKAL, _ACTIVE_IDENTITY
    previous = JACKAL
    previous_identity = _ACTIVE_IDENTITY
    JACKAL = _IntegratedKernelBridge(kernel_call)
    _ACTIVE_IDENTITY = identity_sha256
    _TRACE.clear()
    try:
        validated = _validate_arguments(tool_name, arguments)
        return TOOL_REGISTRY[tool_name][0](validated)
    except Refusal as refusal:
        return refusal_body(refusal.reason, refusal.detail, refusal.non_claims)
    finally:
        JACKAL = previous
        _ACTIVE_IDENTITY = previous_identity


if __name__ == "__main__":
    raise SystemExit(
        "This identity-pinned module is not a standalone server; launch JACKAL instead."
    )
