#!/usr/bin/env python3 -B
"""Additive AI-facing certified STEM engineering workflows for JACKAL.

This module is identity-pinned wrapper orchestration, not a second calculator.
It extends JACKAL toward full STEM coverage with the same trust split used by
the number-theory surface (de Bruijn's criterion): Python may select closed
workflows, parse structure, and search (candidate rational roots, interval
case analysis), but every reported arithmetic claim is verified by delegated
calls into the sealed runtime, and every physical result names its model and
its consequence ceiling.

Surfaces:

- exact Gaussian-rational complex arithmetic with formal-bounded modulus
  enclosures;
- a certified polynomial equation solver: kernel-canonical coefficients,
  kernel-verified rational roots, Sturm-certified isolating intervals for
  every distinct real root, kernel-certified squarefreeness, and honest
  gradation of rational-root-search completeness;
- Routh-Hurwitz stability tables with every entry kernel-computed and the
  interpretation rule named;
- ideal circuit, Euler-Bernoulli beam, and chemistry models that carry their
  assumptions and an advisory ceiling, with formal-bounded square-root,
  logarithm, and arctangent enclosures where an admitted checker exists.

A refusal is an answer.  Marginal Routh cases, unknown elements, and
out-of-model requests refuse with named reasons; nothing silently downgrades
or substitutes local floating-point arithmetic.
"""

from __future__ import annotations

import copy
import math
import re
from fractions import Fraction
from typing import Callable


ENGINEERING_TOOL_NAMES = frozenset(
    {
        "jackal_beam",
        "jackal_chem",
        "jackal_circuit",
        "jackal_complex",
        "jackal_poly_solve",
        "jackal_routh_stability",
    }
)

CONSEQUENCE_CEILING = "informational"
ADVISORY_CEILING = "advisory"
MAX_TOKEN_BYTES = 512
MAX_EXPRESSION_BYTES = 2048
MAX_BUILT_EXPRESSION_BYTES = 8192
MAX_COMPLEX_EXPONENT = 64
MAX_SOLVE_DEGREE = 32
MAX_ROUTH_DEGREE = 24
MAX_RATIONAL_CANDIDATES = 512
MAX_RATIONAL_CONSTANT = 10**12
MAX_CIRCUIT_VALUES = 32
MAX_FORMULA_BYTES = 256
MAX_FORMULA_DEPTH = 8
MAX_GROUP_COUNT = 9999
MAX_TOTAL_ATOMS = 1_000_000

RATIONAL_TOKEN = re.compile(
    r"(?:"
    r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?"
    r"|-?(?:0|[1-9][0-9]*)\.[0-9]+"
    r"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?[eE][+-]?[0-9]+"
    r")\Z",
    re.ASCII,
)
CANONICAL_NONNEGATIVE_INTEGER = re.compile(r"(?:0|[1-9][0-9]*)\Z", re.ASCII)
FORMULA_TOKEN = re.compile(r"([A-Z][a-z]?|\(|\)|[0-9]+)", re.ASCII)

# IUPAC standard atomic weights of the elements 2021 (conventional single
# values for the note-5 interval elements), transcribed from
# https://iupac.qmul.ac.uk/AtWt/AtWt21.html.  Declared data, not measurement.
ATOMIC_WEIGHT_SOURCE = (
    "IUPAC standard atomic weights 2021 (conventional values for interval "
    "elements); https://iupac.qmul.ac.uk/AtWt/AtWt21.html"
)
ATOMIC_WEIGHTS = {
    "H": "1.008", "He": "4.002602", "Li": "6.94", "Be": "9.0121831",
    "B": "10.81", "C": "12.011", "N": "14.007", "O": "15.999",
    "F": "18.998403162", "Ne": "20.1797", "Na": "22.98976928", "Mg": "24.305",
    "Al": "26.9815384", "Si": "28.085", "P": "30.973761998", "S": "32.06",
    "Cl": "35.45", "Ar": "39.95", "K": "39.0983", "Ca": "40.078",
    "Sc": "44.955907", "Ti": "47.867", "V": "50.9415", "Cr": "51.9961",
    "Mn": "54.938043", "Fe": "55.845", "Co": "58.933194", "Ni": "58.6934",
    "Cu": "63.546", "Zn": "65.38", "Ga": "69.723", "Ge": "72.630",
    "As": "74.921595", "Se": "78.971", "Br": "79.904", "Kr": "83.798",
    "Rb": "85.4678", "Sr": "87.62", "Y": "88.905838", "Zr": "91.224",
    "Nb": "92.90637", "Mo": "95.95", "Ru": "101.07", "Rh": "102.90549",
    "Pd": "106.42", "Ag": "107.8682", "Cd": "112.414", "In": "114.818",
    "Sn": "118.710", "Sb": "121.760", "Te": "127.60", "I": "126.90447",
    "Xe": "131.293", "Cs": "132.90545196", "Ba": "137.327", "La": "138.90547",
    "Ce": "140.116", "Pr": "140.90766", "Nd": "144.242", "Sm": "150.36",
    "Eu": "151.964", "Gd": "157.25", "Tb": "158.925354", "Dy": "162.500",
    "Ho": "164.930329", "Er": "167.259", "Tm": "168.934219", "Yb": "173.045",
    "Lu": "174.9668", "Hf": "178.486", "Ta": "180.94788", "W": "183.84",
    "Re": "186.207", "Os": "190.23", "Ir": "192.217", "Pt": "195.084",
    "Au": "196.966570", "Hg": "200.592", "Tl": "204.38", "Pb": "207.2",
    "Bi": "208.98040", "Th": "232.0377", "Pa": "231.03588", "U": "238.02891",
}

# SI 2019 defining constants (exact by definition of the SI units).
BOLTZMANN_EXACT = "1.380649e-23"
AVOGADRO_EXACT = "6.02214076e23"


class Refusal(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


_KERNEL: object | None = None
_IDENTITY: str | None = None
_TRACE: list[dict] = []


def _identity() -> str:
    if _IDENTITY is None:
        raise RuntimeError(
            "engineering identity is unavailable outside integrated dispatch"
        )
    return _IDENTITY


def _refusal(reason: str, detail: str) -> dict:
    return {
        "status": "refused",
        "reason": reason,
        "detail": detail,
        "consequence_ceiling": CONSEQUENCE_CEILING,
        "identities": {"jackal_engineering_sha256": _identity()},
        "non_claims": [
            "A refusal is an answer; no weaker lane or local arithmetic was substituted",
            "No algebraic, stability, circuit, structural, or chemical conclusion was established",
        ],
    }


def _kernel_call(tool: str, arguments: dict) -> dict:
    if _KERNEL is None:
        raise Refusal("kernel-unavailable", "engineering module is not attached to JACKAL")
    result = _KERNEL.call(tool, arguments)
    if not isinstance(result, dict):
        raise Refusal("kernel-error", "JACKAL returned a non-object")
    trace = {
        "tool": tool,
        "arguments": copy.deepcopy(arguments),
        "status": result.get("status", "unknown"),
    }
    fields = result.get("fields")
    if isinstance(fields, dict) and isinstance(fields.get("parsed"), str):
        trace["parsed"] = fields["parsed"]
    _TRACE.append(trace)
    if result.get("status") == "refused":
        raise Refusal(
            f"kernel-refused:{result.get('reason', 'unknown')}",
            str(result.get("detail", "the delegated JACKAL lane refused")),
        )
    return result


def _field(result: dict, key: str, subject: str) -> str:
    fields = result.get("fields")
    if not isinstance(fields, dict) or not isinstance(fields.get(key), str):
        raise Refusal("kernel-error", f"delegated {subject} result omitted field {key!r}")
    return fields[key]


def _exact(expression: str) -> str:
    if len(expression.encode("utf-8")) > MAX_BUILT_EXPRESSION_BYTES:
        raise Refusal("expression-budget", "delegated expression exceeds the wrapper byte budget")
    result = _kernel_call("jackal_exact", {"expression": expression})
    if result.get("status") != "exact":
        raise Refusal("kernel-error", "delegated exact lane returned a non-exact status")
    return _field(result, "exact", "exact")


def _require_zero(expression: str, subject: str) -> str:
    canonical = _exact(expression)
    if canonical != "0":
        raise Refusal("engineering-internal", f"kernel verification failed for {subject}")
    return canonical


def _sign_of(canonical: str) -> int:
    if canonical == "0":
        return 0
    return -1 if canonical.startswith("-") else 1


def _sign(expression: str) -> int:
    return _sign_of(_exact(expression))


def _formal_enclosure(tool: str, expression: str, value: str, subject: str) -> dict:
    result = _kernel_call(
        tool, {"expression": expression, "input_lo": value, "input_hi": value}
    )
    if result.get("status") != "formal-bounded" or result.get("checker_rerun") != "ACCEPT":
        raise Refusal(
            "kernel-error",
            f"{tool} did not return a checker-accepted formal-bounded result for {subject}",
        )
    return result


def _sqrt_formal(radicand: str, subject: str) -> dict:
    if _sign(radicand) < 0:
        raise Refusal("domain", f"{subject} square-root radicand is negative")
    return _formal_enclosure("jackal_sqrt_rat_bound", "sqrt(x)", radicand, subject)


def _ln_formal(value: str, subject: str) -> dict:
    if _sign(value) <= 0:
        raise Refusal("domain", f"{subject} logarithm argument must be positive")
    return _formal_enclosure("jackal_ln_rat_bound", "ln(x)", value, subject)


def _atan_formal(value: str, subject: str) -> dict:
    return _formal_enclosure("jackal_atan_rat_bound", "atan(x)", value, subject)


def _enclosure_endpoints(result: dict, subject: str) -> tuple[str, str]:
    receipt = result.get("receipt")
    inner = receipt.get("result") if isinstance(receipt, dict) else None
    if not isinstance(inner, dict):
        raise Refusal("kernel-error", f"{subject} receipt omitted its result")
    lo = inner.get("enclosure_lo")
    hi = inner.get("enclosure_hi")
    if not isinstance(lo, str) or not isinstance(hi, str):
        raise Refusal("kernel-error", f"{subject} receipt omitted enclosure endpoints")
    return lo, hi


def _token(value: object, subject: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > MAX_TOKEN_BYTES
        or RATIONAL_TOKEN.fullmatch(value) is None
    ):
        raise Refusal(
            "args",
            f"{subject} must be a bounded integer, decimal, scientific literal, or rational",
        )
    return value


def _positive(arguments: dict, key: str, subject: str) -> str:
    value = _token(arguments.get(key), subject)
    if _sign(value) <= 0:
        raise Refusal("domain", f"{subject} must be strictly positive")
    return value


def _result(
    lane: str,
    status: str,
    ceiling: str,
    parsed: dict,
    fields: dict,
    field_status: dict,
    non_claims: list[str],
    assumptions: list[str] | None = None,
) -> dict:
    result = {
        "status": status,
        "lane": lane,
        "formal": False,
        "consequence_ceiling": ceiling,
        "parsed": parsed,
        "fields": fields,
        "field_status": field_status,
        "delegated_to": list(_TRACE),
        "identities": {"jackal_engineering_sha256": _identity()},
        "non_claims": non_claims,
    }
    if assumptions is not None:
        result["assumptions"] = assumptions
    return result


_BASE_NON_CLAIMS = [
    "Every reported arithmetic claim was verified by delegated sealed-runtime calls; the wrapper's workflow selection is identity-pinned and tested, not Lean-proved",
    "The delegation trace is reproducibility metadata, not an independent certificate",
]


# --------------------------------------------------------------------------
# jackal_complex — exact Gaussian-rational arithmetic
# --------------------------------------------------------------------------


def _complex_pair(arguments: dict, prefix: str) -> tuple[str, str]:
    return (
        _token(arguments.get(f"{prefix}_re"), f"{prefix}_re"),
        _token(arguments.get(f"{prefix}_im"), f"{prefix}_im"),
    )


def _complex_mul(a: tuple[str, str], b: tuple[str, str]) -> tuple[str, str]:
    re_part = _exact(f"(({a[0]})*({b[0]}))-(({a[1]})*({b[1]}))")
    im_part = _exact(f"(({a[0]})*({b[1]}))+(({a[1]})*({b[0]}))")
    return re_part, im_part


def _complex_tool(arguments: dict) -> dict:
    operation = arguments.get("operation")
    binary = {"add", "subtract", "multiply", "divide"}
    unary = {"conjugate", "modulus", "power"}
    if operation not in binary | unary:
        raise Refusal("operation-unknown", "complex operation is outside the closed route table")
    a = _complex_pair(arguments, "a")
    fields: dict[str, object] = {}
    field_status: dict[str, str] = {}
    non_claims = list(_BASE_NON_CLAIMS)
    if operation in binary:
        b = _complex_pair(arguments, "b")
        if operation == "add":
            fields["re"] = _exact(f"({a[0]})+({b[0]})")
            fields["im"] = _exact(f"({a[1]})+({b[1]})")
        elif operation == "subtract":
            fields["re"] = _exact(f"({a[0]})-({b[0]})")
            fields["im"] = _exact(f"({a[1]})-({b[1]})")
        elif operation == "multiply":
            fields["re"], fields["im"] = _complex_mul(a, b)
        else:
            denominator = _exact(f"(({b[0]})*({b[0]}))+(({b[1]})*({b[1]}))")
            if denominator == "0":
                raise Refusal("domain", "complex division by zero")
            fields["re"] = _exact(
                f"((({a[0]})*({b[0]}))+(({a[1]})*({b[1]})))/({denominator})"
            )
            fields["im"] = _exact(
                f"((({a[1]})*({b[0]}))-(({a[0]})*({b[1]})))/({denominator})"
            )
            fields["denominator"] = denominator
        field_status.update({"re": "exact", "im": "exact"})
    elif operation == "conjugate":
        fields["re"] = _exact(f"({a[0]})")
        fields["im"] = _exact(f"-({a[1]})")
        field_status.update({"re": "exact", "im": "exact"})
    elif operation == "modulus":
        modulus_squared = _exact(f"(({a[0]})*({a[0]}))+(({a[1]})*({a[1]}))")
        fields["modulus_squared"] = modulus_squared
        field_status["modulus_squared"] = "exact"
        if modulus_squared == "0":
            fields["modulus"] = "0"
            field_status["modulus"] = "exact"
        else:
            fields["modulus_enclosure"] = _sqrt_formal(modulus_squared, "modulus")
            field_status["modulus_enclosure"] = "formal-bounded"
        non_claims.append(
            "The modulus enclosure certifies only the admitted sqrt fragment on the exact radicand"
        )
    else:
        exponent_token = arguments.get("exponent")
        if (
            not isinstance(exponent_token, str)
            or CANONICAL_NONNEGATIVE_INTEGER.fullmatch(exponent_token) is None
            or int(exponent_token) > MAX_COMPLEX_EXPONENT
        ):
            raise Refusal(
                "args",
                f"exponent must be a canonical integer between 0 and {MAX_COMPLEX_EXPONENT}",
            )
        exponent = int(exponent_token)
        result_pair = (_exact("1"), _exact("0"))
        base_pair = (_exact(f"({a[0]})"), _exact(f"({a[1]})"))
        remaining = exponent
        while remaining > 0:
            if remaining % 2 == 1:
                result_pair = _complex_mul(result_pair, base_pair)
            remaining //= 2
            if remaining > 0:
                base_pair = _complex_mul(base_pair, base_pair)
        fields["re"], fields["im"] = result_pair
        fields["exponent"] = exponent_token
        field_status.update({"re": "exact", "im": "exact"})
    return _result(
        "engineering-complex-exact-delegated-v1",
        "exact",
        CONSEQUENCE_CEILING,
        {"operation": operation, "arguments": copy.deepcopy(arguments)},
        fields,
        field_status,
        non_claims,
    )


# --------------------------------------------------------------------------
# jackal_poly_solve — certified polynomial equation solving over Q[x]
# --------------------------------------------------------------------------


def _poly_canon(expression: str) -> tuple[list[str], int]:
    result = _kernel_call("jackal_poly_canon", {"expression": expression})
    degree = _field(result, "degree", "poly-canon")
    coeffs = _field(result, "coeffs", "poly-canon").split(",")
    return coeffs, int(degree)


def _poly_expression(coeffs: list[str]) -> str:
    terms = []
    for power, coeff in enumerate(coeffs):
        if coeff == "0":
            continue
        if power == 0:
            terms.append(f"({coeff})")
        elif power == 1:
            terms.append(f"({coeff})*x")
        else:
            terms.append(f"({coeff})*x^{power}")
    return "+".join(terms) if terms else "0"


def _poly_value_expression(coeffs: list[str], point: str) -> str:
    terms = []
    for power, coeff in enumerate(coeffs):
        if coeff == "0":
            continue
        if power == 0:
            terms.append(f"({coeff})")
        else:
            terms.append(f"({coeff})*({point})^{power}")
    return "+".join(terms) if terms else "0"


def _fraction_of(token: str) -> Fraction:
    if "/" in token:
        numerator, denominator = token.split("/", 1)
        return Fraction(int(numerator), int(denominator))
    return Fraction(int(token))


def _bounded_divisors(value: int) -> list[int] | None:
    value = abs(value)
    if value == 0 or value > MAX_RATIONAL_CONSTANT:
        return None
    divisors: list[int] = []
    step = 1
    while step * step <= value:
        if value % step == 0:
            divisors.append(step)
            other = value // step
            if other != step:
                divisors.append(other)
            if len(divisors) > MAX_RATIONAL_CANDIDATES:
                return None
        step += 1
    return sorted(divisors)


def _poly_solve_tool(arguments: dict) -> dict:
    expression = arguments.get("expression")
    if (
        not isinstance(expression, str)
        or not expression
        or len(expression.encode("utf-8")) > MAX_EXPRESSION_BYTES
    ):
        raise Refusal("args", "expression must be a bounded Q[x] polynomial")
    coeffs, degree = _poly_canon(expression)
    if degree < 0:
        raise Refusal("poly-zero", "the zero polynomial has every number as a root")
    if degree == 0:
        return _result(
            "engineering-poly-solve-exact-delegated-v1",
            "exact",
            CONSEQUENCE_CEILING,
            {"expression": expression},
            {"degree": "0", "coefficients": coeffs, "verdict": "no-roots"},
            {"verdict": "exact"},
            _BASE_NON_CLAIMS
            + ["A nonzero constant polynomial has no roots; the canonical form is kernel-certified"],
        )
    if degree > MAX_SOLVE_DEGREE:
        raise Refusal(
            "poly-budget", f"degree exceeds the solver budget of {MAX_SOLVE_DEGREE}"
        )
    isolate = _kernel_call("jackal_roots_isolate", {"expression": expression})
    distinct_real = int(_field(isolate, "distinct-real-roots", "roots-isolate"))
    isolate_cert = _field(isolate, "exact_cert", "roots-isolate")
    intervals_text = _field(isolate, "intervals", "roots-isolate")
    intervals: list[list[str]] = []
    if intervals_text:
        for chunk in intervals_text.strip("[]").split("]["):
            if chunk:
                low, high = chunk.split(",")
                intervals.append([low, high])
    if len(intervals) != distinct_real:
        raise Refusal("engineering-internal", "isolating intervals disagree with the root count")

    # Kernel-verified integer scaling for the rational root theorem.
    denominators = [_fraction_of(c).denominator for c in coeffs]
    scale = 1
    for denominator in denominators:
        scale = scale * denominator // math.gcd(scale, denominator)
        if scale > MAX_RATIONAL_CONSTANT:
            scale = 0
            break
    scaled: list[int] = []
    search_state = "complete"
    if scale == 0:
        search_state = "incomplete-budget"
    else:
        for coeff in coeffs:
            token = _exact(f"({coeff})*({scale})")
            if "/" in token:
                raise Refusal("engineering-internal", "coefficient scaling was not integral")
            scaled.append(int(token))
    rational_roots: list[dict] = []
    if search_state == "complete":
        trailing_index = next(
            (index for index, value in enumerate(scaled) if value != 0), None
        )
        if trailing_index is None:
            raise Refusal("engineering-internal", "scaled polynomial vanished")
        candidates: set[Fraction] = set()
        if trailing_index > 0:
            candidates.add(Fraction(0))
        numerators = _bounded_divisors(scaled[trailing_index])
        denominators_set = _bounded_divisors(scaled[degree])
        if numerators is None or denominators_set is None or (
            len(numerators) * len(denominators_set) * 2 > MAX_RATIONAL_CANDIDATES * 4
        ):
            search_state = "incomplete-budget"
        else:
            for numerator in numerators:
                for denominator in denominators_set:
                    candidates.add(Fraction(numerator, denominator))
                    candidates.add(Fraction(-numerator, denominator))
            for candidate in sorted(candidates):
                token = (
                    str(candidate.numerator)
                    if candidate.denominator == 1
                    else f"{candidate.numerator}/{candidate.denominator}"
                )
                value = _exact(_poly_value_expression(coeffs, token))
                if value != "0":
                    continue
                matched_index = None
                for index, (low, high) in enumerate(intervals):
                    if _fraction_of(low) <= candidate <= _fraction_of(high):
                        matched_index = index
                        break
                if matched_index is not None:
                    low, high = intervals[matched_index]
                    if _sign(f"({token})-({low})") < 0 or _sign(f"({high})-({token})") < 0:
                        raise Refusal(
                            "engineering-internal",
                            "a verified rational root escaped its isolating interval",
                        )
                rational_roots.append(
                    {
                        "root": token,
                        "value_check": value,
                        "interval_index": (
                            str(matched_index) if matched_index is not None else "unmatched"
                        ),
                    }
                )

    # Kernel-certified squarefreeness via gcd with the power-rule derivative.
    derivative_coeffs = [
        _exact(f"({coeffs[power]})*({power})") for power in range(1, degree + 1)
    ]
    derivative_expression = _poly_expression(derivative_coeffs)
    gcd_result = _kernel_call(
        "jackal_poly_gcd",
        {"lhs": expression, "rhs": derivative_expression},
    )
    gcd_coeffs = _field(gcd_result, "gcd", "poly-gcd").split(",")
    squarefree = len(gcd_coeffs) == 1
    fields: dict[str, object] = {
        "degree": str(degree),
        "coefficients": coeffs,
        "distinct_real_roots": str(distinct_real),
        "isolating_intervals": intervals,
        "isolation_certificate": isolate_cert,
        "rational_roots": rational_roots,
        "rational_root_search": search_state,
        "squarefree": "true" if squarefree else "false",
        "gcd_with_derivative": gcd_coeffs,
    }
    field_status = {
        "degree": "exact",
        "coefficients": "exact",
        "distinct_real_roots": "exact",
        "isolating_intervals": "exact",
        "rational_roots": "exact",
        "squarefree": "exact",
    }
    non_claims = _BASE_NON_CLAIMS + [
        "Isolating intervals and the distinct-real-root count carry the sealed Sturm certificate; each listed rational root was verified to evaluate to the kernel zero",
        "Squarefreeness is the kernel gcd of the polynomial with its power-rule derivative; the derivative construction is a named syntactic rule",
    ]
    if search_state == "complete":
        irrational = distinct_real - sum(
            1 for root in rational_roots if root["interval_index"] != "unmatched"
        )
        fields["irrational_real_roots"] = str(irrational)
        field_status["irrational_real_roots"] = "exact"
        non_claims.append(
            "Irrationality of the unmatched intervals follows from the rational root theorem over the kernel-verified scaled integer coefficients with complete divisor enumeration"
        )
    else:
        non_claims.append(
            "The rational-root search hit its enumeration budget; unmatched intervals are NOT claimed irrational"
        )
    if squarefree:
        fields["nonreal_root_count"] = str(degree - distinct_real)
        field_status["nonreal_root_count"] = "exact"
        non_claims.append(
            "The non-real count uses the fundamental theorem of algebra on a kernel-certified squarefree polynomial"
        )
    return _result(
        "engineering-poly-solve-exact-delegated-v1",
        "exact",
        CONSEQUENCE_CEILING,
        {"expression": expression},
        fields,
        field_status,
        non_claims,
    )


# --------------------------------------------------------------------------
# jackal_routh_stability — Routh-Hurwitz tables with kernel-exact entries
# --------------------------------------------------------------------------


def _routh_tool(arguments: dict) -> dict:
    expression = arguments.get("expression")
    if (
        not isinstance(expression, str)
        or not expression
        or len(expression.encode("utf-8")) > MAX_EXPRESSION_BYTES
    ):
        raise Refusal("args", "expression must be a bounded characteristic polynomial in x")
    coeffs, degree = _poly_canon(expression)
    if degree < 1:
        raise Refusal("routh-degree", "the characteristic polynomial must have degree >= 1")
    if degree > MAX_ROUTH_DEGREE:
        raise Refusal("routh-budget", f"degree exceeds the Routh budget of {MAX_ROUTH_DEGREE}")
    descending = list(reversed(coeffs))
    width = degree // 2 + 1
    row_zero = [
        descending[index] if index < len(descending) else "0"
        for index in range(0, degree + 1, 2)
    ]
    row_one = [
        descending[index] if index < len(descending) else "0"
        for index in range(1, degree + 1, 2)
    ]
    row_zero += ["0"] * (width - len(row_zero))
    row_one += ["0"] * (width - len(row_one))
    table = [row_zero, row_one]
    for _ in range(2, degree + 1):
        upper = table[-2]
        lower = table[-1]
        pivot = lower[0]
        if pivot == "0":
            raise Refusal(
                "routh-singular",
                "a zero first-column pivot occurred; epsilon and auxiliary-polynomial continuations are not implemented, so marginal or symmetric-root cases refuse",
            )
        row = []
        for index in range(width):
            upper_next = upper[index + 1] if index + 1 < width else "0"
            lower_next = lower[index + 1] if index + 1 < width else "0"
            row.append(
                _exact(
                    f"((({pivot})*({upper_next}))-(({upper[0]})*({lower_next})))/({pivot})"
                )
            )
        table.append(row)
    first_column = [row[0] for row in table]
    signs = [_sign_of(value) for value in first_column]
    if any(sign == 0 for sign in signs):
        raise Refusal(
            "routh-singular",
            "a zero first-column entry occurred; the sign-change count is undefined without a continuation method",
        )
    sign_changes = sum(
        1 for previous, current in zip(signs, signs[1:]) if previous != current
    )
    verdict = "stable" if sign_changes == 0 else "unstable"
    return _result(
        "engineering-routh-exact-delegated-v1",
        "exact",
        CONSEQUENCE_CEILING,
        {"expression": expression},
        {
            "degree": str(degree),
            "coefficients_descending": descending,
            "routh_table": table,
            "first_column": first_column,
            "sign_changes": str(sign_changes),
            "right_half_plane_roots": str(sign_changes),
            "verdict": verdict,
        },
        {
            "routh_table": "exact",
            "first_column": "exact",
            "sign_changes": "exact",
            "right_half_plane_roots": "exact",
            "verdict": "exact",
        },
        _BASE_NON_CLAIMS
        + [
            "Every Routh entry is a delegated kernel-exact rational; the step from sign changes to right-half-plane root count is the named Routh-Hurwitz criterion",
            "The verdict concerns the supplied polynomial only, never a physical system, plant model, discretization, or implementation",
        ],
    )


# --------------------------------------------------------------------------
# jackal_circuit — ideal lumped-element models
# --------------------------------------------------------------------------


def _value_list(arguments: dict, key: str, subject: str) -> list[str]:
    values = arguments.get(key)
    if (
        not isinstance(values, list)
        or not values
        or len(values) > MAX_CIRCUIT_VALUES
    ):
        raise Refusal("args", f"{subject} must be a nonempty bounded array of tokens")
    return [_token(value, f"{subject}[{index}]") for index, value in enumerate(values)]


def _circuit_tool(arguments: dict) -> dict:
    operation = arguments.get("operation")
    fields: dict[str, object] = {}
    field_status: dict[str, str] = {}
    assumptions = ["ideal lumped linear components", "exact caller-declared component values", "consistent SI units supplied by the caller"]
    non_claims = list(_BASE_NON_CLAIMS)
    if operation == "series_resistance":
        values = _value_list(arguments, "values", "values")
        for value in values:
            if _sign(value) < 0:
                raise Refusal("domain", "resistances must be nonnegative")
        fields["resistance"] = _exact("+".join(f"({value})" for value in values))
        field_status["resistance"] = "exact"
    elif operation == "parallel_resistance":
        values = _value_list(arguments, "values", "values")
        for value in values:
            if _sign(value) <= 0:
                raise Refusal("domain", "parallel resistances must be strictly positive")
        fields["resistance"] = _exact(
            "1/(" + "+".join(f"1/({value})" for value in values) + ")"
        )
        field_status["resistance"] = "exact"
    elif operation == "voltage_divider":
        v_in = _token(arguments.get("v_in"), "v_in")
        r1 = _positive(arguments, "r1", "r1")
        r2 = _positive(arguments, "r2", "r2")
        fields["v_out"] = _exact(f"({v_in})*({r2})/(({r1})+({r2}))")
        field_status["v_out"] = "exact"
        assumptions.append("unloaded divider output")
    elif operation == "rc_time_constant":
        resistance = _positive(arguments, "resistance", "resistance")
        capacitance = _positive(arguments, "capacitance", "capacitance")
        fields["time_constant"] = _exact(f"({resistance})*({capacitance})")
        field_status["time_constant"] = "exact"
    elif operation == "rl_time_constant":
        resistance = _positive(arguments, "resistance", "resistance")
        inductance = _positive(arguments, "inductance", "inductance")
        fields["time_constant"] = _exact(f"({inductance})/({resistance})")
        field_status["time_constant"] = "exact"
    elif operation == "resonant_omega":
        inductance = _positive(arguments, "inductance", "inductance")
        capacitance = _positive(arguments, "capacitance", "capacitance")
        omega_squared = _exact(f"1/(({inductance})*({capacitance}))")
        fields["omega_squared"] = omega_squared
        fields["omega_enclosure"] = _sqrt_formal(omega_squared, "resonant omega")
        field_status.update(
            {"omega_squared": "exact", "omega_enclosure": "formal-bounded"}
        )
        non_claims.append(
            "The cyclic frequency f0 = omega/(2*pi) is not reported: pi has no admitted exact lane"
        )
    elif operation == "rlc_series_impedance":
        resistance = _positive(arguments, "resistance", "resistance")
        inductance = _positive(arguments, "inductance", "inductance")
        capacitance = _positive(arguments, "capacitance", "capacitance")
        omega = _positive(arguments, "omega", "omega")
        reactance = _exact(
            f"(({omega})*({inductance}))-(1/(({omega})*({capacitance})))"
        )
        magnitude_squared = _exact(
            f"(({resistance})*({resistance}))+(({reactance})*({reactance}))"
        )
        phase_tangent = _exact(f"({reactance})/({resistance})")
        fields.update(
            {
                "resistance": resistance,
                "reactance": reactance,
                "impedance_magnitude_squared": magnitude_squared,
                "impedance_enclosure": _sqrt_formal(magnitude_squared, "impedance"),
                "phase_tangent": phase_tangent,
                "phase_enclosure_radians": _atan_formal(phase_tangent, "phase"),
            }
        )
        field_status.update(
            {
                "reactance": "exact",
                "impedance_magnitude_squared": "exact",
                "impedance_enclosure": "formal-bounded",
                "phase_tangent": "exact",
                "phase_enclosure_radians": "formal-bounded",
            }
        )
        assumptions.append("sinusoidal steady state at the supplied angular frequency")
    elif operation == "power":
        voltage = arguments.get("voltage")
        current = arguments.get("current")
        resistance = arguments.get("resistance")
        supplied = [value is not None for value in (voltage, current, resistance)]
        if sum(supplied) != 2:
            raise Refusal("args", "power requires exactly two of voltage, current, resistance")
        if voltage is not None and current is not None:
            v = _token(voltage, "voltage")
            i = _token(current, "current")
            fields["power"] = _exact(f"({v})*({i})")
        elif voltage is not None:
            v = _token(voltage, "voltage")
            r = _positive(arguments, "resistance", "resistance")
            fields["power"] = _exact(f"(({v})*({v}))/({r})")
        else:
            i = _token(current, "current")
            r = _positive(arguments, "resistance", "resistance")
            fields["power"] = _exact(f"(({i})*({i}))*({r})")
        field_status["power"] = "exact"
    else:
        raise Refusal("operation-unknown", "circuit operation is outside the closed model table")
    non_claims.append(
        "Component tolerances, parasitics, temperature, nonlinearity, and loading are outside the ideal model; no circuit decision may exceed the advisory ceiling"
    )
    return _result(
        f"engineering-circuit-{operation}-v1",
        "model-based",
        ADVISORY_CEILING,
        {"operation": operation, "arguments": copy.deepcopy(arguments)},
        fields,
        field_status,
        non_claims,
        assumptions,
    )


# --------------------------------------------------------------------------
# jackal_beam — Euler-Bernoulli closed-form cases
# --------------------------------------------------------------------------


def _beam_tool(arguments: dict) -> dict:
    operation = arguments.get("operation")
    cases = {
        "cantilever_end_load",
        "cantilever_udl",
        "simply_supported_center_load",
        "simply_supported_udl",
    }
    if operation not in cases:
        raise Refusal("operation-unknown", "beam case is outside the closed model table")
    length = _positive(arguments, "length", "length")
    elastic_modulus = _positive(arguments, "elastic_modulus", "elastic_modulus")
    second_moment = _positive(arguments, "second_moment", "second_moment")
    stiffness = f"(({elastic_modulus})*({second_moment}))"
    fields: dict[str, object] = {}
    if operation == "cantilever_end_load":
        load = _positive(arguments, "point_load", "point_load")
        fields["max_deflection"] = _exact(
            f"(({load})*({length})^3)/(3*{stiffness})"
        )
        fields["max_moment"] = _exact(f"({load})*({length})")
        fields["support_reaction"] = _exact(f"({load})")
    elif operation == "cantilever_udl":
        load = _positive(arguments, "distributed_load", "distributed_load")
        fields["max_deflection"] = _exact(
            f"(({load})*({length})^4)/(8*{stiffness})"
        )
        fields["max_moment"] = _exact(f"(({load})*({length})^2)/2")
        fields["support_reaction"] = _exact(f"({load})*({length})")
    elif operation == "simply_supported_center_load":
        load = _positive(arguments, "point_load", "point_load")
        fields["max_deflection"] = _exact(
            f"(({load})*({length})^3)/(48*{stiffness})"
        )
        fields["max_moment"] = _exact(f"(({load})*({length}))/4")
        fields["support_reaction"] = _exact(f"({load})/2")
    else:
        load = _positive(arguments, "distributed_load", "distributed_load")
        fields["max_deflection"] = _exact(
            f"(5*({load})*({length})^4)/(384*{stiffness})"
        )
        fields["max_moment"] = _exact(f"(({load})*({length})^2)/8")
        fields["support_reaction"] = _exact(f"(({load})*({length}))/2")
    field_status = {key: "exact" for key in fields}
    return _result(
        f"engineering-beam-{operation}-v1",
        "model-based",
        ADVISORY_CEILING,
        {"operation": operation, "arguments": copy.deepcopy(arguments)},
        fields,
        field_status,
        _BASE_NON_CLAIMS
        + [
            "Closed-form Euler-Bernoulli results are exact arithmetic inside a declared idealized model, never a structural design certification",
            "Shear deformation, buckling, lateral-torsional effects, local stresses, self-weight, dynamic loads, and safety factors are outside the model",
            "No structural decision may exceed the advisory consequence ceiling of this wrapper result",
        ],
        [
            "Euler-Bernoulli beam theory (plane sections, small deflections)",
            "linear elastic homogeneous prismatic member",
            "static load exactly as declared; consistent units supplied by the caller",
        ],
    )


# --------------------------------------------------------------------------
# jackal_chem — molar mass, ideal gas, dilution, pH enclosure
# --------------------------------------------------------------------------


def _parse_formula(formula: str) -> dict[str, int]:
    if (
        not isinstance(formula, str)
        or not formula
        or len(formula.encode("utf-8")) > MAX_FORMULA_BYTES
    ):
        raise Refusal("args", "formula must be a bounded chemical formula")
    tokens = FORMULA_TOKEN.findall(formula)
    if "".join(tokens) != formula:
        raise Refusal("chem-formula", "formula contains unsupported characters")
    stack: list[dict[str, int]] = [{}]
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "(":
            if len(stack) > MAX_FORMULA_DEPTH:
                raise Refusal("chem-formula", "formula nesting exceeds the depth budget")
            stack.append({})
            index += 1
        elif token == ")":
            if len(stack) == 1:
                raise Refusal("chem-formula", "unbalanced parenthesis in formula")
            group = stack.pop()
            multiplier = 1
            if index + 1 < len(tokens) and tokens[index + 1].isdigit():
                multiplier = int(tokens[index + 1])
                index += 1
            if multiplier == 0 or multiplier > MAX_GROUP_COUNT:
                raise Refusal("chem-formula", "group multiplier is outside the budget")
            for element, count in group.items():
                stack[-1][element] = stack[-1].get(element, 0) + count * multiplier
            index += 1
        elif token.isdigit():
            raise Refusal("chem-formula", "a count must follow an element or group")
        else:
            element = token
            if element not in ATOMIC_WEIGHTS:
                raise Refusal(
                    "chem-element-unknown",
                    f"element {element!r} is not in the declared IUPAC 2021 table subset",
                )
            count = 1
            if index + 1 < len(tokens) and tokens[index + 1].isdigit():
                count = int(tokens[index + 1])
                index += 1
            if count == 0 or count > MAX_GROUP_COUNT:
                raise Refusal("chem-formula", "element count is outside the budget")
            stack[-1][element] = stack[-1].get(element, 0) + count
            index += 1
    if len(stack) != 1:
        raise Refusal("chem-formula", "unbalanced parenthesis in formula")
    composition = stack[0]
    if not composition or sum(composition.values()) > MAX_TOTAL_ATOMS:
        raise Refusal("chem-formula", "formula is empty or exceeds the atom budget")
    return composition


def _chem_tool(arguments: dict) -> dict:
    operation = arguments.get("operation")
    fields: dict[str, object] = {}
    field_status: dict[str, str] = {}
    assumptions: list[str]
    non_claims = list(_BASE_NON_CLAIMS)
    if operation == "molar_mass":
        composition = _parse_formula(arguments.get("formula"))
        ordered = sorted(composition)
        terms = [
            f"({composition[element]})*({ATOMIC_WEIGHTS[element]})"
            for element in ordered
        ]
        fields["molar_mass_g_per_mol"] = _exact("+".join(terms))
        fields["composition"] = [
            {
                "element": element,
                "count": str(composition[element]),
                "atomic_weight": ATOMIC_WEIGHTS[element],
            }
            for element in ordered
        ]
        field_status.update(
            {"molar_mass_g_per_mol": "exact", "composition": "exact"}
        )
        assumptions = [
            ATOMIC_WEIGHT_SOURCE,
            "normal terrestrial isotopic composition; conventional single values for interval elements",
        ]
        non_claims.append(
            "Atomic weights are declared IUPAC data carried as given inputs; isotopically enriched or geologically unusual material is outside the declared table"
        )
    elif operation == "ideal_gas":
        solve_for = arguments.get("solve_for")
        slots = {"pressure": "P", "volume": "V", "moles": "n", "temperature": "T"}
        if solve_for not in slots:
            raise Refusal("args", "solve_for must be pressure, volume, moles, or temperature")
        supplied: dict[str, str] = {}
        for name in slots:
            if name == solve_for:
                if arguments.get(name) is not None:
                    raise Refusal("args", f"{name} is being solved for and must be omitted")
                continue
            supplied[name] = _positive(arguments, name, name)
        gas_constant = _exact(f"({BOLTZMANN_EXACT})*({AVOGADRO_EXACT})")
        fields["gas_constant_J_per_mol_K"] = gas_constant
        if solve_for == "pressure":
            solved = _exact(
                f"(({supplied['moles']})*({gas_constant})*({supplied['temperature']}))/({supplied['volume']})"
            )
        elif solve_for == "volume":
            solved = _exact(
                f"(({supplied['moles']})*({gas_constant})*({supplied['temperature']}))/({supplied['pressure']})"
            )
        elif solve_for == "moles":
            solved = _exact(
                f"(({supplied['pressure']})*({supplied['volume']}))/(({gas_constant})*({supplied['temperature']}))"
            )
        else:
            solved = _exact(
                f"(({supplied['pressure']})*({supplied['volume']}))/(({gas_constant})*({supplied['moles']}))"
            )
        fields[solve_for] = solved
        field_status.update({solve_for: "exact", "gas_constant_J_per_mol_K": "exact"})
        assumptions = [
            "ideal gas equation of state PV = nRT",
            "R computed from the SI-exact defining constants k and N_A (2019 SI)",
            "SI units: Pa, m^3, mol, K",
        ]
        non_claims.append(
            "Real-gas behavior, phase changes, and mixtures are outside the ideal model"
        )
    elif operation == "dilution":
        c1 = _positive(arguments, "c1", "c1")
        v1 = _positive(arguments, "v1", "v1")
        c2 = arguments.get("c2")
        v2 = arguments.get("v2")
        if (c2 is None) == (v2 is None):
            raise Refusal("args", "dilution requires exactly one of c2 or v2")
        if c2 is None:
            v2_token = _positive(arguments, "v2", "v2")
            fields["c2"] = _exact(f"(({c1})*({v1}))/({v2_token})")
            field_status["c2"] = "exact"
        else:
            c2_token = _positive(arguments, "c2", "c2")
            fields["v2"] = _exact(f"(({c1})*({v1}))/({c2_token})")
            field_status["v2"] = "exact"
        assumptions = ["conservation of dissolved moles (C1*V1 = C2*V2)", "ideal mixing; no volume contraction"]
    elif operation == "ph_enclosure":
        concentration = _positive(arguments, "h_concentration", "h_concentration")
        ln_h = _ln_formal(concentration, "hydrogen-ion concentration")
        ln_ten = _ln_formal("10", "ln(10)")
        h_lo, h_hi = _enclosure_endpoints(ln_h, "ln(h)")
        ten_lo, ten_hi = _enclosure_endpoints(ln_ten, "ln(10)")
        if _sign(ten_lo) <= 0:
            raise Refusal("engineering-internal", "ln(10) enclosure lost positivity")
        # pH = -ln(h)/ln(10); numerator interval [p, q] = [-h_hi, -h_lo].
        p = _exact(f"-({h_hi})")
        q = _exact(f"-({h_lo})")
        if _sign_of(p) >= 0:
            ph_lo = _exact(f"({p})/({ten_hi})")
            ph_hi = _exact(f"({q})/({ten_lo})")
        elif _sign_of(q) <= 0:
            ph_lo = _exact(f"({p})/({ten_lo})")
            ph_hi = _exact(f"({q})/({ten_hi})")
        else:
            ph_lo = _exact(f"({p})/({ten_lo})")
            ph_hi = _exact(f"({q})/({ten_lo})")
        if _sign(f"({ph_hi})-({ph_lo})") < 0:
            raise Refusal("engineering-internal", "pH interval endpoints are out of order")
        fields.update(
            {
                "ph_enclosure_lo": ph_lo,
                "ph_enclosure_hi": ph_hi,
                "ln_h_enclosure": ln_h,
                "ln_ten_enclosure": ln_ten,
            }
        )
        field_status.update(
            {
                "ph_enclosure_lo": "bounded",
                "ph_enclosure_hi": "bounded",
                "ln_h_enclosure": "formal-bounded",
                "ln_ten_enclosure": "formal-bounded",
            }
        )
        assumptions = [
            "pH = -log10(a_H+) with activity approximated by the declared concentration (ideal dilute solution)",
        ]
        non_claims.append(
            "The composed pH interval is bounded, not formal-bounded: the monotone interval-division step is identity-pinned wrapper orchestration over kernel-exact endpoints and Lean-checked ln enclosures"
        )
    else:
        raise Refusal("operation-unknown", "chem operation is outside the closed model table")
    non_claims.append(
        "No laboratory, purity, temperature, or measurement claim is made; declared inputs remain unverified data"
    )
    return _result(
        f"engineering-chem-{operation}-v1",
        "model-based",
        ADVISORY_CEILING,
        {"operation": operation, "arguments": copy.deepcopy(arguments)},
        fields,
        field_status,
        non_claims,
        assumptions,
    )


def dispatch_integrated(
    name: str,
    arguments: dict,
    kernel_call: Callable[[str, dict], dict],
    identity: str,
) -> dict:
    global _KERNEL, _IDENTITY, _TRACE
    if name not in ENGINEERING_TOOL_NAMES or not isinstance(arguments, dict):
        return {
            "status": "refused",
            "reason": "tool-unknown",
            "detail": "engineering tool name or arguments are invalid",
        }

    class Kernel:
        @staticmethod
        def call(tool: str, delegated_arguments: dict) -> dict:
            return kernel_call(tool, delegated_arguments)

    _KERNEL = Kernel()
    _IDENTITY = identity
    _TRACE = []
    try:
        if name == "jackal_complex":
            return _complex_tool(arguments)
        if name == "jackal_poly_solve":
            return _poly_solve_tool(arguments)
        if name == "jackal_routh_stability":
            return _routh_tool(arguments)
        if name == "jackal_circuit":
            return _circuit_tool(arguments)
        if name == "jackal_beam":
            return _beam_tool(arguments)
        return _chem_tool(arguments)
    except Refusal as error:
        return _refusal(error.reason, error.detail)
    except Exception:
        return _refusal("engineering-error", "engineering orchestration failed closed")
    finally:
        _KERNEL = None
        _IDENTITY = None
        _TRACE = []


def _schema(properties: dict, required: list[str]) -> dict:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _definition(name: str, title: str, description: str, schema: dict) -> dict:
    return {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": schema,
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }


def _string(description: str) -> dict:
    return {"type": "string", "description": description}


def tool_definitions() -> list[dict]:
    return [
        _definition(
            "jackal_complex",
            "JACKAL exact complex arithmetic",
            "Exact Gaussian-rational complex arithmetic: add, subtract, multiply, divide, conjugate, integer powers, and modulus with an exact modulus-squared plus a Lean-checked formal-bounded modulus enclosure. Every component delegates to jackal_exact.",
            _schema(
                {
                    "operation": {"type": "string", "enum": ["add", "subtract", "multiply", "divide", "conjugate", "modulus", "power"]},
                    "a_re": _string("Real part of the first operand."),
                    "a_im": _string("Imaginary part of the first operand."),
                    "b_re": _string("Real part of the second operand (binary operations)."),
                    "b_im": _string("Imaginary part of the second operand (binary operations)."),
                    "exponent": _string("Canonical nonnegative integer exponent for power."),
                },
                ["operation", "a_re", "a_im"],
            ),
        ),
        _definition(
            "jackal_poly_solve",
            "JACKAL certified polynomial solver",
            "Certified equation solving over Q[x]: kernel-canonical coefficients, kernel-verified rational roots with isolating-interval placement, the sealed Sturm certificate for every distinct real root, kernel-certified squarefreeness, and honestly graded rational-root-search completeness. Unmatched intervals are claimed irrational only under a complete rational-root enumeration.",
            _schema(
                {"expression": _string("Polynomial in x over Q using + - * / ^ and parentheses.")},
                ["expression"],
            ),
        ),
        _definition(
            "jackal_routh_stability",
            "JACKAL Routh-Hurwitz stability",
            "Routh-Hurwitz analysis of a characteristic polynomial: every table entry is a delegated kernel-exact rational, sign changes count right-half-plane roots by the named criterion, and marginal zero-pivot cases refuse instead of using epsilon heuristics. The verdict concerns the polynomial, never a physical system.",
            _schema(
                {"expression": _string("Characteristic polynomial in x over Q.")},
                ["expression"],
            ),
        ),
        _definition(
            "jackal_circuit",
            "JACKAL ideal circuit models",
            "Ideal lumped-element circuit workflows: series/parallel resistance, voltage divider, RC/RL time constants, resonant angular frequency, series RLC impedance with formal-bounded magnitude and phase enclosures, and DC power. Model-based with declared assumptions and an advisory ceiling.",
            _schema(
                {
                    "operation": {"type": "string", "enum": ["series_resistance", "parallel_resistance", "voltage_divider", "rc_time_constant", "rl_time_constant", "resonant_omega", "rlc_series_impedance", "power"]},
                    "values": {"type": "array", "items": {"type": "string"}, "description": "Component values for series/parallel operations."},
                    "v_in": _string("Divider input voltage."),
                    "r1": _string("Divider upper resistance."),
                    "r2": _string("Divider lower resistance."),
                    "resistance": _string("Resistance value."),
                    "capacitance": _string("Capacitance value."),
                    "inductance": _string("Inductance value."),
                    "omega": _string("Angular frequency for impedance."),
                    "voltage": _string("Voltage for power."),
                    "current": _string("Current for power."),
                },
                ["operation"],
            ),
        ),
        _definition(
            "jackal_beam",
            "JACKAL Euler-Bernoulli beam cases",
            "Closed-form Euler-Bernoulli beam results (cantilever and simply supported, point and uniformly distributed loads): exact maximum deflection, maximum moment, and reactions inside a declared idealized model. Model-based with an advisory ceiling; never a structural design certification.",
            _schema(
                {
                    "operation": {"type": "string", "enum": ["cantilever_end_load", "cantilever_udl", "simply_supported_center_load", "simply_supported_udl"]},
                    "length": _string("Span length."),
                    "elastic_modulus": _string("Young's modulus E."),
                    "second_moment": _string("Second moment of area I."),
                    "point_load": _string("Point load P (point-load cases)."),
                    "distributed_load": _string("Uniform load intensity w (UDL cases)."),
                },
                ["operation", "length", "elastic_modulus", "second_moment"],
            ),
        ),
        _definition(
            "jackal_chem",
            "JACKAL chemistry models",
            "Chemistry workflows over declared data: exact molar mass from the IUPAC 2021 atomic-weight table, ideal-gas solving with the SI-exact gas constant, dilution, and a pH enclosure composed from Lean-checked logarithm enclosures. Model-based with declared assumptions and an advisory ceiling.",
            _schema(
                {
                    "operation": {"type": "string", "enum": ["molar_mass", "ideal_gas", "dilution", "ph_enclosure"]},
                    "formula": _string("Chemical formula, e.g. C6H12O6 or Ca(OH)2."),
                    "solve_for": {"type": "string", "enum": ["pressure", "volume", "moles", "temperature"]},
                    "pressure": _string("Pressure in Pa."),
                    "volume": _string("Volume in m^3."),
                    "moles": _string("Amount of substance in mol."),
                    "temperature": _string("Temperature in K."),
                    "c1": _string("Initial concentration."),
                    "v1": _string("Initial volume."),
                    "c2": _string("Final concentration (solve v2 when omitted)."),
                    "v2": _string("Final volume (solve c2 when omitted)."),
                    "h_concentration": _string("Hydrogen-ion concentration in mol/L."),
                },
                ["operation"],
            ),
        ),
    ]


if __name__ == "__main__":
    raise SystemExit(
        "engineering.py is an identity-pinned JACKAL module, not a standalone service"
    )
