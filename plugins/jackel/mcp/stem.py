#!/usr/bin/env python3 -B
"""Additive AI-facing STEM workflows for JACKAL's single MCP surface.

This module is identity-pinned wrapper orchestration, not a second calculator.
Every numeric value returned by a workflow is obtained from a delegated JACKAL
lane.  Python selects and presents workflows, validates structure, and renders
views; it does not silently substitute local floating-point arithmetic when a
kernel lane refuses.

The linked workspace is a visualization of delegated results.  Its pixels,
SVG geometry, hover interpolation, and layout are never mathematical evidence.
"""

from __future__ import annotations

import copy
import decimal
import hashlib
import html
import json
import re
from typing import Callable


STEM_TOOL_NAMES = frozenset(
    {
        "jackal_aerospace",
        "jackal_hypothesis",
        "jackal_linked_workspace",
        "jackal_matrix",
        "jackal_probability",
        "jackal_regression",
        "jackal_sensor",
    }
)

CONSEQUENCE_CEILING = "informational"
MAX_TOKEN_BYTES = 512
MAX_EXPRESSION_BYTES = 2048
MAX_MATRIX_ROWS = 8
MAX_MATRIX_COLUMNS = 8
MAX_REGRESSION_POINTS = 128
MAX_POLYNOMIAL_DEGREE = 5
MAX_PROBABILITY_TRIALS = 512
MAX_SENSOR_SAMPLES = 512
MIN_WORKSPACE_SAMPLES = 17
MAX_WORKSPACE_SAMPLES = 257
MAX_RESOURCE_TEXT_BYTES = 2 * 1024 * 1024

RATIONAL_TOKEN = re.compile(
    r"(?:"
    r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?"
    r"|-?(?:0|[1-9][0-9]*)\.[0-9]+"
    r"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?[eE][+-]?[0-9]+"
    r")\Z",
    re.ASCII,
)
CANONICAL_INTEGER = re.compile(r"(?:0|[1-9][0-9]*)\Z", re.ASCII)
SAFE_LABEL = re.compile(r"[A-Za-z0-9_.:/+-]{1,128}\Z", re.ASCII)
X_TOKEN = re.compile(r"(?<![A-Za-z0-9_])x(?![A-Za-z0-9_])", re.ASCII)


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
        raise RuntimeError("STEM identity is unavailable outside integrated dispatch")
    return _IDENTITY


def _refusal(reason: str, detail: str) -> dict:
    return {
        "status": "refused",
        "reason": reason,
        "detail": detail,
        "consequence_ceiling": CONSEQUENCE_CEILING,
        "identities": {"jackal_stem_sha256": _identity()},
        "non_claims": [
            "A refusal is an answer; no weaker lane or local arithmetic was substituted",
            "No mathematical, statistical, sensor, aerospace, or visual conclusion was established",
        ],
    }


def _kernel_call(tool: str, arguments: dict, *, allow_refusal: bool = False) -> dict:
    if _KERNEL is None:
        raise Refusal("kernel-unavailable", "STEM module is not attached to JACKAL")
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
    if isinstance(result.get("engine_output"), str):
        trace["engine_output"] = result["engine_output"]
    _TRACE.append(trace)
    if result.get("status") == "refused" and not allow_refusal:
        raise Refusal(
            f"kernel-refused:{result.get('reason', 'unknown')}",
            str(result.get("detail", "the delegated JACKAL lane refused")),
        )
    return result


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


def _integer(value: object, subject: str, *, maximum: int) -> tuple[str, int]:
    if (
        not isinstance(value, str)
        or CANONICAL_INTEGER.fullmatch(value) is None
        or len(value) > 6
    ):
        raise Refusal("args", f"{subject} must be a canonical nonnegative integer string")
    parsed = int(value)
    if parsed > maximum:
        raise Refusal("budget", f"{subject} exceeds the admitted resource budget")
    return value, parsed


def _label(value: object, subject: str) -> str:
    if not isinstance(value, str) or SAFE_LABEL.fullmatch(value) is None:
        raise Refusal("args", f"{subject} must be a bounded ASCII identifier")
    return value


def _exact(expression: str) -> str:
    result = _kernel_call("jackal_exact", {"expression": expression})
    fields = result.get("fields")
    exact = fields.get("exact") if isinstance(fields, dict) else None
    if (
        result.get("status") != "exact"
        or result.get("formal") is not False
        or not isinstance(exact, str)
    ):
        raise Refusal("kernel-error", "jackal_exact returned no canonical exact value")
    return exact


def _evaluate(expression: str) -> tuple[str, dict]:
    result = _kernel_call("jackal_evaluate", {"expression": expression})
    rendered = result.get("engine_output")
    if (
        result.get("status") != "estimated"
        or result.get("formal") is not False
        or not isinstance(rendered, str)
    ):
        raise Refusal("kernel-error", "jackal_evaluate returned no estimated value")
    return rendered, result


def _add(left: str, right: str) -> str:
    return _exact(f"({left})+({right})")


def _sub(left: str, right: str) -> str:
    return _exact(f"({left})-({right})")


def _mul(left: str, right: str) -> str:
    return _exact(f"({left})*({right})")


def _div(left: str, right: str) -> str:
    return _exact(f"({left})/({right})")


def _neg(value: str) -> str:
    return _exact(f"-({value})")


def _sum(values: list[str]) -> str:
    if not values:
        return _exact("0")
    return _exact("+".join(f"({value})" for value in values))


def _count_exact(count: int) -> str:
    if count <= 0:
        return _exact("0")
    return _exact("+".join("1" for _ in range(count)))


def _sign(value: str) -> int:
    canonical = _exact(value)
    if canonical == "0":
        return 0
    if canonical.startswith("-"):
        return -1
    return 1


def _compare(left: str, right: str) -> int:
    return _sign(f"({left})-({right})")


def _require_positive(value: str, subject: str) -> None:
    if _compare(value, "0") <= 0:
        raise Refusal("domain", f"{subject} must be strictly positive")


def _matrix(value: object, subject: str) -> list[list[str]]:
    if not isinstance(value, list) or not value or len(value) > MAX_MATRIX_ROWS:
        raise Refusal("matrix-shape", f"{subject} must be a nonempty bounded row array")
    width: int | None = None
    result: list[list[str]] = []
    for row_index, row in enumerate(value):
        if not isinstance(row, list) or not row or len(row) > MAX_MATRIX_COLUMNS:
            raise Refusal("matrix-shape", f"{subject}[{row_index}] is not a bounded row")
        if width is None:
            width = len(row)
        if len(row) != width:
            raise Refusal("matrix-shape", f"{subject} rows must have equal length")
        result.append(
            [_exact(_token(cell, f"{subject}[{row_index}][{column_index}]"))
             for column_index, cell in enumerate(row)]
        )
    return result


def _matrix_clone(matrix: list[list[str]]) -> list[list[str]]:
    return [list(row) for row in matrix]


def _matrix_rref_values(matrix: list[list[str]]) -> tuple[list[list[str]], int]:
    values = _matrix_clone(matrix)
    rows = len(values)
    columns = len(values[0])
    pivot_row = 0
    for column in range(columns):
        if pivot_row >= rows:
            break
        selected: int | None = None
        for candidate in range(pivot_row, rows):
            if _sign(values[candidate][column]) != 0:
                selected = candidate
                break
        if selected is None:
            continue
        if selected != pivot_row:
            values[pivot_row], values[selected] = values[selected], values[pivot_row]
        pivot = values[pivot_row][column]
        values[pivot_row] = [_div(cell, pivot) for cell in values[pivot_row]]
        for row in range(rows):
            if row == pivot_row or _sign(values[row][column]) == 0:
                continue
            factor = values[row][column]
            values[row] = [
                _exact(f"({values[row][item]})-({factor})*({values[pivot_row][item]})")
                for item in range(columns)
            ]
        pivot_row += 1
    return values, pivot_row


def _matrix_determinant(matrix: list[list[str]]) -> str:
    size = len(matrix)
    if len(matrix[0]) != size:
        raise Refusal("matrix-shape", "determinant requires a square matrix")
    values = _matrix_clone(matrix)
    determinant = _exact("1")
    odd_swaps = False
    for column in range(size):
        selected: int | None = None
        for candidate in range(column, size):
            if _sign(values[candidate][column]) != 0:
                selected = candidate
                break
        if selected is None:
            return _exact("0")
        if selected != column:
            values[column], values[selected] = values[selected], values[column]
            odd_swaps = not odd_swaps
        pivot = values[column][column]
        determinant = _mul(determinant, pivot)
        for row in range(column + 1, size):
            if _sign(values[row][column]) == 0:
                continue
            factor = _div(values[row][column], pivot)
            for item in range(column, size):
                values[row][item] = _exact(
                    f"({values[row][item]})-({factor})*({values[column][item]})"
                )
    if odd_swaps:
        determinant = _neg(determinant)
    return determinant


def _matrix_inverse(matrix: list[list[str]]) -> list[list[str]]:
    size = len(matrix)
    if len(matrix[0]) != size:
        raise Refusal("matrix-shape", "inverse requires a square matrix")
    augmented: list[list[str]] = []
    for row in range(size):
        identity = ["1" if row == column else "0" for column in range(size)]
        augmented.append(list(matrix[row]) + identity)
    reduced, rank = _matrix_rref_values(augmented)
    if rank != size:
        raise Refusal("matrix-singular", "matrix has no exact inverse")
    for row in range(size):
        for column in range(size):
            expected = "1" if row == column else "0"
            if _compare(reduced[row][column], expected) != 0:
                raise Refusal("matrix-singular", "matrix has no exact inverse")
    return [row[size:] for row in reduced]


def _matrix_solve(matrix: list[list[str]], vector: object) -> list[str]:
    size = len(matrix)
    if len(matrix[0]) != size:
        raise Refusal("matrix-shape", "solve requires a square coefficient matrix")
    if not isinstance(vector, list) or len(vector) != size:
        raise Refusal("matrix-shape", "vector length must equal the matrix row count")
    rhs = [
        _exact(_token(item, f"vector[{index}]"))
        for index, item in enumerate(vector)
    ]
    augmented = [list(matrix[row]) + [rhs[row]] for row in range(size)]
    reduced, rank = _matrix_rref_values(augmented)
    if rank != size:
        raise Refusal("matrix-nonunique", "system does not have one exact solution")
    for row in range(size):
        for column in range(size):
            expected = "1" if row == column else "0"
            if _compare(reduced[row][column], expected) != 0:
                raise Refusal("matrix-nonunique", "system does not have one exact solution")
    return [row[-1] for row in reduced]


def _matrix_tool(arguments: dict) -> dict:
    operation = arguments.get("operation")
    if operation not in {"add", "determinant", "inverse", "multiply", "rref", "solve", "transpose"}:
        raise Refusal("operation-unknown", "matrix operation is outside the closed route table")
    matrix = _matrix(arguments.get("matrix"), "matrix")
    fields: dict[str, object] = {}
    field_status: dict[str, str] = {}
    if operation == "transpose":
        fields["matrix"] = [list(column) for column in zip(*matrix)]
        field_status["matrix"] = "exact"
    elif operation == "determinant":
        fields["determinant"] = _matrix_determinant(matrix)
        field_status["determinant"] = "exact"
    elif operation == "rref":
        reduced, rank = _matrix_rref_values(matrix)
        fields["matrix"] = reduced
        fields["rank"] = _count_exact(rank)
        field_status.update({"matrix": "exact", "rank": "exact"})
    elif operation == "inverse":
        fields["matrix"] = _matrix_inverse(matrix)
        field_status["matrix"] = "exact"
    elif operation == "solve":
        fields["solution"] = _matrix_solve(matrix, arguments.get("vector"))
        field_status["solution"] = "exact"
    else:
        second = _matrix(arguments.get("second_matrix"), "second_matrix")
        if operation == "add":
            if len(second) != len(matrix) or len(second[0]) != len(matrix[0]):
                raise Refusal("matrix-shape", "matrix addition requires identical shapes")
            fields["matrix"] = [
                [_add(matrix[row][column], second[row][column])
                 for column in range(len(matrix[0]))]
                for row in range(len(matrix))
            ]
        else:
            if len(matrix[0]) != len(second):
                raise Refusal("matrix-shape", "matrix multiplication inner dimensions differ")
            product: list[list[str]] = []
            for row in range(len(matrix)):
                out_row: list[str] = []
                for column in range(len(second[0])):
                    terms = [
                        f"({matrix[row][item]})*({second[item][column]})"
                        for item in range(len(second))
                    ]
                    out_row.append(_exact("+".join(terms)))
                product.append(out_row)
            fields["matrix"] = product
        field_status["matrix"] = "exact"
    return {
        "status": "exact",
        "lane": "matrix-exact-delegated-v1",
        "formal": False,
        "consequence_ceiling": CONSEQUENCE_CEILING,
        "parsed": {
            "operation": operation,
            "matrix": matrix,
            "second_matrix": arguments.get("second_matrix"),
            "vector": arguments.get("vector"),
        },
        "fields": fields,
        "field_status": field_status,
        "delegated_to": list(_TRACE),
        "identities": {"jackal_stem_sha256": _identity()},
        "non_claims": [
            "Every reported numeric matrix field was produced by delegated status=exact JACKAL rational calls",
            "NOT formal-bounded: the row-operation orchestration is identity-pinned and tested, not Lean-proved",
            "The delegation trace is reproducibility metadata, not an independent matrix certificate",
            "No conditioning, measurement provenance, or physical interpretation is inferred",
        ],
    }


def _regression_tool(arguments: dict) -> dict:
    model = arguments.get("model")
    if model != "polynomial_ols":
        raise Refusal("operation-unknown", "regression currently admits polynomial_ols")
    raw_x = arguments.get("x")
    raw_y = arguments.get("y")
    if (
        not isinstance(raw_x, list)
        or not isinstance(raw_y, list)
        or len(raw_x) != len(raw_y)
        or len(raw_x) < 2
        or len(raw_x) > MAX_REGRESSION_POINTS
    ):
        raise Refusal("sample-shape", "x and y must be equal bounded arrays with at least two points")
    x = [_token(value, f"x[{index}]") for index, value in enumerate(raw_x)]
    y = [_token(value, f"y[{index}]") for index, value in enumerate(raw_y)]
    degree_text, degree = _integer(
        arguments.get("degree"), "degree", maximum=MAX_POLYNOMIAL_DEGREE
    )
    if degree < 1 or degree >= len(x):
        raise Refusal("model-rank", "degree must be positive and below the sample count")
    width = degree + 1
    normal: list[list[str]] = []
    rhs: list[str] = []
    for row in range(width):
        normal_row: list[str] = []
        for column in range(width):
            exponent = row + column
            normal_row.append(
                _sum([f"({value})^{exponent}" for value in x])
                if exponent > 0 else _count_exact(len(x))
            )
        normal.append(normal_row)
        rhs.append(
            _sum(
                [
                    f"({y[index]})*({x[index]})^{row}"
                    if row > 0 else y[index]
                    for index in range(len(x))
                ]
            )
        )
    coefficients = _matrix_solve(normal, rhs)
    fitted: list[str] = []
    for value in x:
        terms = [
            coefficients[power]
            if power == 0 else f"({coefficients[power]})*({value})^{power}"
            for power in range(width)
        ]
        fitted.append(_exact("+".join(f"({term})" for term in terms)))
    residual_squares = [
        f"(({y[index]})-({fitted[index]}))^2" for index in range(len(y))
    ]
    sse = _sum(residual_squares)
    mean_y = _div(_sum(y), _count_exact(len(y)))
    sst = _sum([f"(({value})-({mean_y}))^2" for value in y])
    r_squared: str | None = None
    if _sign(sst) != 0:
        r_squared = _exact(f"1-({sse})/({sst})")
    expression = "+".join(
        coefficients[power]
        if power == 0
        else f"({coefficients[power]})*x^{power}"
        for power in range(width)
    )
    fields: dict[str, object] = {
        "coefficients_ascending": coefficients,
        "expression": expression,
        "fitted": fitted,
        "sse": sse,
        "sst": sst,
        "r_squared": r_squared,
        "normal_matrix": normal,
        "normal_rhs": rhs,
    }
    return {
        "status": "model-based",
        "lane": "regression-polynomial-ols-exact-fields-v1",
        "formal": False,
        "consequence_ceiling": CONSEQUENCE_CEILING,
        "parsed": {"model": model, "degree": degree_text, "x": x, "y": y},
        "fields": fields,
        "field_status": {
            "coefficients_ascending": "exact",
            "fitted": "exact",
            "sse": "exact",
            "sst": "exact",
            "r_squared": "undefined" if r_squared is None else "exact",
        },
        "assumptions": [
            "ordinary least squares under the caller-selected polynomial basis",
            "the supplied x and y tokens are treated as exact rational data",
        ],
        "delegated_to": list(_TRACE),
        "identities": {"jackal_stem_sha256": _identity()},
        "non_claims": [
            "Exact coefficients do not establish that a polynomial model is appropriate",
            "No distribution, independence, homoscedasticity, confidence interval, prediction interval, or causal interpretation is inferred",
            "Supplied points are not promoted to measured or representative data",
            "NOT formal-bounded: exact rational fields are outside the Lean certificate chain",
        ],
    }


def _binomial_pmf(n_text: str, n: int, k_text: str, k: int, p: str) -> str:
    if k > n:
        raise Refusal("domain", "k must not exceed n")
    complement = _exact(f"({n_text})-({k_text})")
    coefficient = "1"
    for step in range(1, min(k, n - k) + 1):
        coefficient = _exact(
            f"({coefficient})*(({n_text})-({step})+1)/({step})"
        )
    return _exact(
        f"({coefficient})*({p})^({k_text})*(1-({p}))^({complement})"
    )


def _binomial_probability_range(
    n_text: str, n: int, start: int, stop: int, p: str
) -> list[str]:
    """Produce consecutive exact PMFs with one recurrence call per new term."""
    if start < 0 or stop < start or stop > n:
        raise Refusal("domain", "binomial probability range is invalid")
    if p == "0":
        return [_exact("1" if index == 0 else "0") for index in range(start, stop + 1)]
    if p == "1":
        return [_exact("1" if index == n else "0") for index in range(start, stop + 1)]
    probabilities = [_binomial_pmf(n_text, n, str(start), start, p)]
    current = probabilities[0]
    for index in range(start, stop):
        current = _exact(
            f"({current})*(({n_text})-({index}))/(({index})+1)*({p})/(1-({p}))"
        )
        probabilities.append(current)
    return probabilities


def _probability_tool(arguments: dict) -> dict:
    operation = arguments.get("operation")
    if operation not in {"binomial_cdf", "binomial_pmf", "normal_cdf"}:
        raise Refusal("operation-unknown", "probability operation is outside the closed route table")
    assumptions: list[str]
    fields: dict[str, object]
    field_status: dict[str, str]
    if operation.startswith("binomial"):
        n_text, n = _integer(arguments.get("n"), "n", maximum=MAX_PROBABILITY_TRIALS)
        k_text, k = _integer(arguments.get("k"), "k", maximum=MAX_PROBABILITY_TRIALS)
        p = _exact(_token(arguments.get("p"), "p"))
        if k > n or _compare(p, "0") < 0 or _compare(p, "1") > 0:
            raise Refusal("domain", "binomial requires 0 <= k <= n and 0 <= p <= 1")
        if operation == "binomial_pmf":
            probability = _binomial_pmf(n_text, n, k_text, k, p)
        else:
            probability = _sum(_binomial_probability_range(n_text, n, 0, k, p))
        fields = {"probability": probability}
        field_status = {"probability": "exact"}
        assumptions = [
            "fixed trial count",
            "independent Bernoulli trials",
            "constant caller-supplied success probability",
        ]
    else:
        z = _token(arguments.get("z"), "z")
        cutoff = _token(arguments.get("tail_cutoff"), "tail_cutoff")
        tolerance = _token(arguments.get("tolerance"), "tolerance")
        _require_positive(cutoff, "tail_cutoff")
        _require_positive(tolerance, "tolerance")
        if _compare(z, _neg(cutoff)) < 0 or _compare(z, cutoff) > 0:
            raise Refusal("domain", "z must lie inside the caller-declared finite tail cutoff")
        result = _kernel_call(
            "jackal_integrate_adaptive",
            {
                "expression": "exp(-x^2/2)/sqrt(2*pi)",
                "input_lo": _neg(cutoff),
                "input_hi": z,
                "tolerance": tolerance,
            },
        )
        result_fields = result.get("fields")
        probability = result_fields.get("integral") if isinstance(result_fields, dict) else None
        if (
            result.get("status") != "estimated"
            or result.get("formal") is not False
            or not isinstance(probability, str)
        ):
            raise Refusal("kernel-error", "normal CDF integration returned no integral field")
        fields = {
            "finite_cutoff_cdf_estimate": probability,
            "integration_result": result,
            "omitted_left_tail_below": _neg(cutoff),
        }
        field_status = {"finite_cutoff_cdf_estimate": "estimated"}
        assumptions = ["standard normal model", "caller-selected finite tail cutoff"]
    return {
        "status": "model-based",
        "lane": f"probability-{operation}-v1",
        "formal": False,
        "consequence_ceiling": CONSEQUENCE_CEILING,
        "parsed": copy.deepcopy(arguments),
        "fields": fields,
        "field_status": field_status,
        "assumptions": assumptions,
        "delegated_to": list(_TRACE),
        "identities": {"jackal_stem_sha256": _identity()},
        "non_claims": [
            "A probability computed under a declared distribution does not establish that the data-generating process follows that distribution",
            "No input provenance, independence, calibration, or sampling design is verified",
            "Normal CDF output is an estimate over a finite caller-selected interval, not a bound on the full infinite-tail probability",
        ],
    }


def _hypothesis_tool(arguments: dict) -> dict:
    operation = arguments.get("operation")
    alternative = arguments.get("alternative")
    if alternative not in {"less", "greater", "two_sided"}:
        raise Refusal("args", "alternative must be less, greater, or two_sided")
    if operation == "one_sample_z":
        mean = _token(arguments.get("sample_mean"), "sample_mean")
        null = _token(arguments.get("null_mean"), "null_mean")
        sigma = _token(arguments.get("population_sd"), "population_sd")
        n_text, _unused_n = _integer(
            arguments.get("n"), "n", maximum=MAX_PROBABILITY_TRIALS
        )
        cutoff = _token(arguments.get("tail_cutoff"), "tail_cutoff")
        tolerance = _token(arguments.get("tolerance"), "tolerance")
        _require_positive(sigma, "population_sd")
        _require_positive(n_text, "n")
        _require_positive(cutoff, "tail_cutoff")
        z_expression = f"(({mean})-({null}))/(({sigma})/sqrt({n_text}))"
        z, z_result = _evaluate(z_expression)
        absolute_z, absolute_result = _evaluate(f"abs({z_expression})")
        lower = _neg(cutoff)
        if _compare(z, lower) < 0 or _compare(z, cutoff) > 0:
            raise Refusal(
                "domain",
                "the estimated z statistic lies outside the caller-declared finite tail cutoff",
            )
        if alternative == "less":
            integration_lo, integration_hi = lower, z
            multiplier = "1"
        elif alternative == "greater":
            integration_lo, integration_hi = z, cutoff
            multiplier = "1"
        else:
            integration_lo, integration_hi = absolute_z, cutoff
            multiplier = "2"
        tail = _kernel_call(
            "jackal_integrate_adaptive",
            {
                "expression": "exp(-x^2/2)/sqrt(2*pi)",
                "input_lo": integration_lo,
                "input_hi": integration_hi,
                "tolerance": tolerance,
            },
        )
        tail_fields = tail.get("fields")
        tail_value = tail_fields.get("integral") if isinstance(tail_fields, dict) else None
        if (
            tail.get("status") != "estimated"
            or tail.get("formal") is not False
            or not isinstance(tail_value, str)
        ):
            raise Refusal("kernel-error", "z-test integration returned no integral field")
        p_value, p_result = _evaluate(f"({multiplier})*({tail_value})")
        fields = {
            "z": z,
            "p_value_estimate": p_value,
            "z_result": z_result,
            "absolute_z_result": absolute_result,
            "tail_integration_result": tail,
            "p_value_render_result": p_result,
        }
        field_status = {"z": "estimated", "p_value_estimate": "estimated"}
        assumptions = [
            "known caller-supplied population standard deviation",
            "independent representative observations",
            "normal sampling distribution for the standardized mean",
            "caller-selected finite normal-tail cutoff",
        ]
    elif operation == "exact_binomial_tail":
        n_text, n = _integer(arguments.get("n"), "n", maximum=MAX_PROBABILITY_TRIALS)
        k_text, k = _integer(arguments.get("k"), "k", maximum=MAX_PROBABILITY_TRIALS)
        p0 = _exact(_token(arguments.get("p0"), "p0"))
        if alternative == "two_sided":
            raise Refusal(
                "test-definition-ambiguous",
                "two-sided exact binomial tests have multiple conventions; choose less or greater",
            )
        if k > n or _compare(p0, "0") < 0 or _compare(p0, "1") > 0:
            raise Refusal("domain", "exact binomial tail requires 0 <= k <= n and 0 <= p0 <= 1")
        start, stop = (0, k) if alternative == "less" else (k, n)
        p_value = _sum(_binomial_probability_range(n_text, n, start, stop, p0))
        fields = {"p_value": p_value}
        field_status = {"p_value": "exact"}
        assumptions = [
            "fixed trial count",
            "independent Bernoulli trials",
            "constant null success probability",
            "one-sided exact tail convention",
        ]
    else:
        raise Refusal("operation-unknown", "hypothesis operation is outside the closed route table")
    return {
        "status": "model-based",
        "lane": f"hypothesis-{operation}-v1",
        "formal": False,
        "consequence_ceiling": "advisory",
        "parsed": copy.deepcopy(arguments),
        "fields": fields,
        "field_status": field_status,
        "assumptions": assumptions,
        "delegated_to": list(_TRACE),
        "identities": {"jackal_stem_sha256": _identity()},
        "non_claims": [
            "A p-value is conditional on the declared test model and is not the probability that the null hypothesis is true",
            "A z-test p-value is an estimate over a finite caller-selected tail interval, not a bound on the full infinite-tail probability",
            "No sampling design, independence, distributional fit, multiple-testing correction, effect importance, or decision threshold is verified",
            "This result is not a scientific, medical, engineering, or safety decision",
        ],
    }


def _sorted_exact(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        position = len(result)
        while position > 0 and _compare(value, result[position - 1]) < 0:
            position -= 1
        result.insert(position, value)
    return result


def _sensor_tool(arguments: dict) -> dict:
    operation = arguments.get("operation")
    if operation not in {"ingest_batch", "linear_calibration"}:
        raise Refusal("operation-unknown", "sensor operation is outside the closed route table")
    sensor_id = _label(arguments.get("sensor_id"), "sensor_id")
    channel = _label(arguments.get("channel"), "channel")
    quantity = _label(arguments.get("quantity"), "quantity")
    unit = _label(arguments.get("unit"), "unit")
    source = arguments.get("source")
    observed_at = arguments.get("observed_at")
    if not isinstance(source, str) or not source.strip() or len(source.encode("utf-8")) > 1024:
        raise Refusal("undeclared-datum", "sensor source must be declared")
    if not isinstance(observed_at, str) or not observed_at.strip() or len(observed_at) > 128:
        raise Refusal("undeclared-datum", "sensor observation time must be declared")
    raw_samples = arguments.get("samples")
    if (
        not isinstance(raw_samples, list)
        or not raw_samples
        or len(raw_samples) > MAX_SENSOR_SAMPLES
    ):
        raise Refusal("sample-shape", "samples must be a nonempty bounded array")
    samples = [_token(value, f"samples[{index}]") for index, value in enumerate(raw_samples)]
    given: dict[str, object] = {
        "sensor_id": sensor_id,
        "channel": channel,
        "quantity": quantity,
        "unit": unit,
        "source": source,
        "observed_at": observed_at,
        "input_provenance": "supplied",
    }
    if operation == "linear_calibration":
        scale = _token(arguments.get("scale"), "scale")
        offset = _token(arguments.get("offset"), "offset")
        calibration_source = arguments.get("calibration_source")
        calibration_as_of = arguments.get("calibration_as_of")
        if (
            not isinstance(calibration_source, str)
            or not calibration_source.strip()
            or not isinstance(calibration_as_of, str)
            or not calibration_as_of.strip()
        ):
            raise Refusal(
                "undeclared-datum",
                "linear calibration requires calibration_source and calibration_as_of",
            )
        samples = [_exact(f"({scale})*({value})+({offset})") for value in samples]
        given["calibration"] = {
            "model": "y=scale*x+offset",
            "scale": scale,
            "offset": offset,
            "source": calibration_source,
            "as_of": calibration_as_of,
            "verified": False,
        }
    ordered = _sorted_exact(samples)
    count = _count_exact(len(samples))
    total = _sum(samples)
    mean = _div(total, count)
    variance = _div(_sum([f"(({value})-({mean}))^2" for value in samples]), count)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2 == 1
        else _div(_add(ordered[middle - 1], ordered[middle]), "2")
    )
    stddev = _sqrt_formal(variance)
    return {
        "status": "exact-given",
        "lane": "sensor-supplied-batch-v1",
        "formal": False,
        "consequence_ceiling": CONSEQUENCE_CEILING,
        "parsed": {
            "operation": operation,
            "sensor_id": sensor_id,
            "channel": channel,
            "sample_count": count,
        },
        "given": given,
        "fields": {
            "samples": samples,
            "count": count,
            "sum": total,
            "mean": mean,
            "median": median,
            "minimum": ordered[0],
            "maximum": ordered[-1],
            "population_variance": variance,
            "population_stddev_enclosure": stddev,
        },
        "field_status": {
            "samples": "exact-given",
            "count": "exact",
            "sum": "exact-given",
            "mean": "exact-given",
            "median": "exact-given",
            "minimum": "exact-given",
            "maximum": "exact-given",
            "population_variance": "exact-given",
            "population_stddev_enclosure": "formal-bounded",
        },
        "delegated_to": list(_TRACE),
        "identities": {"jackal_stem_sha256": _identity()},
        "non_claims": [
            "The samples, source, timestamps, sensor identity, unit, and calibration metadata are caller-supplied and were not authenticated",
            "This tool does not claim it opened or read physical hardware; browser or device acquisition must remain separately observable",
            "Descriptive summaries do not establish accuracy, calibration, uncertainty, representativeness, independence, or a probability distribution",
            "The standard-deviation field is a formal-bounded enclosure of arithmetic over supplied values, not a certified sensor measurement",
        ],
    }


def _sqrt_formal(radicand: str) -> dict:
    if _compare(radicand, "0") < 0:
        raise Refusal("domain", "aerospace square-root radicand is negative")
    result = _kernel_call(
        "jackal_sqrt_rat_bound",
        {"expression": "sqrt(x)", "input_lo": radicand, "input_hi": radicand},
    )
    if result.get("status") != "formal-bounded" or result.get("checker_rerun") != "ACCEPT":
        raise Refusal(
            "kernel-error",
            "jackal_sqrt_rat_bound did not return a checker-accepted formal-bounded result",
        )
    return result


def _ln_formal(value: str) -> dict:
    _require_positive(value, "logarithm argument")
    result = _kernel_call(
        "jackal_ln_rat_bound",
        {"expression": "ln(x)", "input_lo": value, "input_hi": value},
    )
    if result.get("status") != "formal-bounded" or result.get("checker_rerun") != "ACCEPT":
        raise Refusal(
            "kernel-error",
            "jackal_ln_rat_bound did not return a checker-accepted formal-bounded result",
        )
    return result


def _aerospace_tool(arguments: dict) -> dict:
    operation = arguments.get("operation")
    parameters = arguments.get("parameters")
    if not isinstance(parameters, dict):
        raise Refusal("args", "parameters must be an object")

    def need(name: str) -> str:
        value = _token(parameters.get(name), name)
        _require_positive(value, name)
        return value

    fields: dict[str, object] = {}
    field_status: dict[str, str] = {}
    assumptions: list[str] = []
    if operation == "circular_orbit":
        mu = need("mu")
        radius = need("radius")
        speed_radicand = _exact(f"({mu})/({radius})")
        fields["speed_enclosure"] = _sqrt_formal(speed_radicand)
        period, period_result = _evaluate(f"2*pi*sqrt(({radius})^3/({mu}))")
        fields.update({"period_estimate": period, "period_result": period_result})
        field_status.update({"speed_enclosure": "formal-bounded", "period_estimate": "estimated"})
        assumptions = ["ideal circular two-body orbit", "point masses", "constant supplied gravitational parameter"]
    elif operation == "vis_viva":
        mu = need("mu")
        radius = need("radius")
        semi_major_axis = need("semi_major_axis")
        radicand = _exact(f"({mu})*(2/({radius})-1/({semi_major_axis}))")
        fields["speed_enclosure"] = _sqrt_formal(radicand)
        field_status["speed_enclosure"] = "formal-bounded"
        assumptions = ["ideal Keplerian two-body orbit", "osculating semi-major axis supplied by caller"]
    elif operation == "rocket_equation":
        exhaust_velocity = need("exhaust_velocity")
        initial_mass = need("initial_mass")
        final_mass = need("final_mass")
        if _compare(initial_mass, final_mass) <= 0:
            raise Refusal("domain", "initial_mass must exceed final_mass")
        ratio = _exact(f"({initial_mass})/({final_mass})")
        fields["mass_ratio"] = ratio
        fields["ln_mass_ratio_enclosure"] = _ln_formal(ratio)
        delta_v, delta_v_result = _evaluate(f"({exhaust_velocity})*ln({ratio})")
        fields.update({"delta_v_estimate": delta_v, "delta_v_result": delta_v_result})
        field_status.update(
            {"mass_ratio": "exact", "ln_mass_ratio_enclosure": "formal-bounded", "delta_v_estimate": "estimated"}
        )
        assumptions = ["ideal Tsiolkovsky rocket equation", "constant effective exhaust velocity", "no gravity or drag losses"]
    elif operation == "hohmann_transfer":
        mu = need("mu")
        r1 = need("r1")
        r2 = need("r2")
        if _compare(r1, r2) == 0:
            raise Refusal("domain", "Hohmann transfer radii must differ")
        a_transfer = _exact(f"(({r1})+({r2}))/2")
        v1 = _sqrt_formal(_exact(f"({mu})/({r1})"))
        v2 = _sqrt_formal(_exact(f"({mu})/({r2})"))
        vt1 = _sqrt_formal(_exact(f"({mu})*(2/({r1})-1/({a_transfer}))"))
        vt2 = _sqrt_formal(_exact(f"({mu})*(2/({r2})-1/({a_transfer}))"))
        delta_v, delta_v_result = _evaluate(
            f"abs(sqrt(({mu})*(2/({r1})-1/({a_transfer})))-sqrt(({mu})/({r1})))"
            f"+abs(sqrt(({mu})/({r2}))-sqrt(({mu})*(2/({r2})-1/({a_transfer}))))"
        )
        transfer_time, time_result = _evaluate(f"pi*sqrt(({a_transfer})^3/({mu}))")
        fields.update(
            {
                "transfer_semi_major_axis": a_transfer,
                "initial_circular_speed_enclosure": v1,
                "final_circular_speed_enclosure": v2,
                "transfer_speed_at_r1_enclosure": vt1,
                "transfer_speed_at_r2_enclosure": vt2,
                "total_delta_v_estimate": delta_v,
                "transfer_time_estimate": transfer_time,
                "delta_v_result": delta_v_result,
                "time_result": time_result,
            }
        )
        field_status.update(
            {
                "transfer_semi_major_axis": "exact",
                "initial_circular_speed_enclosure": "formal-bounded",
                "final_circular_speed_enclosure": "formal-bounded",
                "transfer_speed_at_r1_enclosure": "formal-bounded",
                "transfer_speed_at_r2_enclosure": "formal-bounded",
                "total_delta_v_estimate": "estimated",
                "transfer_time_estimate": "estimated",
            }
        )
        assumptions = ["coplanar circular two-body endpoint orbits", "impulsive burns", "no perturbations or finite-burn losses"]
    elif operation == "plane_change":
        velocity = need("velocity")
        angle_degrees = _token(parameters.get("angle_degrees"), "angle_degrees")
        if _compare(angle_degrees, "0") < 0 or _compare(angle_degrees, "180") > 0:
            raise Refusal("domain", "angle_degrees must lie in the closed interval [0,180]")
        delta_v, result = _evaluate(f"2*({velocity})*sin(({angle_degrees})*pi/360)")
        fields.update({"delta_v_estimate": delta_v, "evaluation_result": result})
        field_status["delta_v_estimate"] = "estimated"
        assumptions = ["instantaneous pure plane change", "constant speed across the maneuver", "smallest plane-change angle supplied in degrees"]
    else:
        raise Refusal("operation-unknown", "aerospace operation is outside the closed model table")
    return {
        "status": "model-based",
        "lane": f"aerospace-{operation}-v1",
        "formal": False,
        "consequence_ceiling": "advisory",
        "parsed": {"operation": operation, "parameters": copy.deepcopy(parameters)},
        "fields": fields,
        "field_status": field_status,
        "assumptions": assumptions,
        "delegated_to": list(_TRACE),
        "identities": {"jackal_stem_sha256": _identity()},
        "non_claims": [
            "Formal-bounded scalar subfields certify only admitted arithmetic fragments, not the physical model or mission inputs",
            "No perturbations, uncertainty, navigation error, actuator limits, finite-burn effects, atmosphere, ephemeris, or mission safety are inferred unless explicitly named in the selected model",
            "This workflow is not the published JACKAL spacecraft finite-burn certificate and cannot inherit that certificate's verdict",
            "No aerospace decision may exceed the advisory consequence ceiling of this wrapper result",
        ],
    }


def _json_for_script(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _workspace_document(payload: dict, *, shell: bool = False) -> str:
    data = _json_for_script(payload)
    shell_note = (
        "This static resource is the linked-workspace shell. Call jackal_linked_workspace "
        "to populate it with delegated evidence."
        if shell
        else "Hover the curve or table to move one evidence cursor through every view."
    )
    document = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; font-src 'none';">
<title>JACKAL Linked Evidence Workspace</title>
<style>
:root{
  --void:#080b1a;--flight:#101831;--bay:#151f3b;--plate:#1a2747;
  --telemetry:#73a7ff;--signal:#5de7ca;--reentry:#ff7a66;--amber:#f6c76e;
  --frost:#ecf3ff;--muted:#91a4c4;--danger:#ff7185;
  --line:rgba(145,164,196,.22);--line-hot:rgba(115,167,255,.46);
  --panel:rgba(13,20,43,.94);--shadow:0 24px 70px rgba(1,4,18,.34);
  color-scheme:dark;font-family:"Avenir Next","Segoe UI",ui-sans-serif,sans-serif;
}
*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:var(--void);color:var(--frost)}
body{background:
  radial-gradient(ellipse at 8% -12%,rgba(73,112,255,.24),transparent 38%),
  radial-gradient(ellipse at 105% 32%,rgba(255,122,102,.10),transparent 32%),
  linear-gradient(90deg,rgba(115,167,255,.026) 1px,transparent 1px) 0 0/36px 36px,
  linear-gradient(rgba(115,167,255,.026) 1px,transparent 1px) 0 0/36px 36px,
  var(--void)}
button,input{font:inherit}button:focus-visible,input:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--amber);outline-offset:3px}
.shell{min-height:100vh;display:grid;grid-template-rows:auto 1fr auto;isolation:isolate}
.mast{position:relative;z-index:4;display:grid;grid-template-columns:auto auto minmax(240px,1fr) auto;align-items:center;gap:18px;padding:16px 24px;border-bottom:1px solid var(--line);background:rgba(8,11,26,.88);box-shadow:0 14px 45px rgba(1,4,18,.22);backdrop-filter:blur(18px)}
.mast:before{content:"";position:absolute;inset:0 0 auto;height:2px;background:linear-gradient(90deg,var(--telemetry),var(--signal) 42%,var(--reentry) 78%,transparent)}
.mark{position:relative;width:44px;height:44px;display:grid;place-items:center;border:1px solid var(--telemetry);border-radius:50%;font:800 17px "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;color:var(--frost);box-shadow:inset 0 0 0 5px rgba(115,167,255,.06),0 0 28px rgba(115,167,255,.14)}
.mark:before,.mark:after{content:"";position:absolute;border:1px solid rgba(93,231,202,.55);border-radius:50%;transform:rotate(-24deg)}
.mark:before{width:54px;height:20px}.mark:after{width:6px;height:6px;background:var(--reentry);border:0;right:-2px;top:14px;box-shadow:0 0 12px rgba(255,122,102,.8)}
.brand{display:grid;gap:3px;min-width:190px}.brand strong{font:800 15px/1 "Arial Narrow","Avenir Next Condensed",sans-serif;letter-spacing:.22em}.brand span{font:650 9px "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;color:var(--muted);letter-spacing:.18em}
.expression{min-width:0;display:grid;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:12px;padding:9px 13px;border:1px solid rgba(115,167,255,.18);border-left:3px solid var(--telemetry);background:linear-gradient(90deg,rgba(115,167,255,.10),rgba(115,167,255,.025));box-shadow:inset 0 1px rgba(255,255,255,.025)}
.expression-label{font:750 8px "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;color:var(--telemetry);letter-spacing:.16em;text-transform:uppercase}.expression code{min-width:0;font:600 15px "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;color:var(--frost);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.status-chip{display:flex;align-items:center;gap:8px;padding:8px 11px;border:1px solid currentColor;color:var(--amber);background:rgba(246,199,110,.04);font:750 9px "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;letter-spacing:.12em;text-transform:uppercase}.status-chip:before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;box-shadow:0 0 10px currentColor}.status-chip[data-status="checked"]{color:var(--signal)}.status-chip[data-status="estimated"]{color:var(--reentry)}
.deck{display:grid;grid-template-columns:minmax(0,1fr) 318px;min-height:0}
.work{padding:20px;display:grid;grid-template-rows:minmax(410px,1fr) 216px;gap:16px;min-width:0}
.panel{position:relative;border:1px solid var(--line);background:linear-gradient(148deg,rgba(21,31,59,.96),rgba(9,14,31,.96));box-shadow:var(--shadow),inset 0 1px rgba(255,255,255,.025);clip-path:polygon(0 0,calc(100% - 13px) 0,100% 13px,100% 100%,13px 100%,0 calc(100% - 13px));overflow:hidden}
.panel:after{content:"";position:absolute;right:0;top:0;width:13px;height:13px;border-top:1px solid var(--line-hot);transform:rotate(45deg) translate(3px,-7px);pointer-events:none}
.panel-title{height:44px;display:flex;align-items:center;justify-content:space-between;padding:0 15px;border-bottom:1px solid var(--line);background:linear-gradient(90deg,rgba(115,167,255,.055),transparent 55%);font:750 9px "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;letter-spacing:.16em;color:var(--muted);text-transform:uppercase}
.panel-title span{display:flex;align-items:center;gap:9px}.panel-title span:before{content:"";width:18px;height:2px;background:linear-gradient(90deg,var(--telemetry),var(--signal));box-shadow:0 0 10px rgba(93,231,202,.32)}.panel-title em{font-style:normal;color:var(--signal)}
.graph-wrap{height:calc(100% - 44px);display:grid;grid-template-columns:minmax(0,1fr) 232px;min-height:0}
#plot{width:100%;height:100%;min-height:300px;display:block;background:radial-gradient(ellipse at 50% 108%,rgba(73,112,255,.13),transparent 52%),rgba(4,8,21,.54);cursor:crosshair}
.table-wrap{border-left:1px solid var(--line);overflow:auto;background:rgba(5,9,23,.62);scrollbar-color:var(--plate) transparent}
table{width:100%;border-collapse:collapse;font:11px "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace}th,td{text-align:right;padding:9px 11px;border-bottom:1px solid rgba(145,164,196,.11);white-space:nowrap}th{position:sticky;top:0;background:#111a33;color:var(--muted);z-index:2;font-size:9px;letter-spacing:.08em;text-transform:uppercase}tbody tr{transition:background-color .12s ease,color .12s ease;cursor:crosshair}tbody tr:hover{background:rgba(115,167,255,.07)}tr.active{background:linear-gradient(90deg,rgba(93,231,202,.16),rgba(93,231,202,.04));color:var(--signal);box-shadow:inset 2px 0 var(--signal)}tr.refused{color:var(--danger)}
.lower{display:grid;grid-template-columns:1.15fr .85fr;gap:16px;min-height:0}.readout{padding:16px;display:grid;gap:12px;align-content:start;overflow:auto}.equation{font:600 17px/1.5 "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;color:var(--frost);overflow-wrap:anywhere}.subtle{font-size:12px;line-height:1.55;color:var(--muted)}
.cursor-card{display:grid;grid-template-columns:1fr 1fr;gap:10px}.datum{position:relative;padding:12px 13px;border:1px solid rgba(115,167,255,.12);background:linear-gradient(135deg,rgba(115,167,255,.10),rgba(93,231,202,.035))}.datum:before{content:"";position:absolute;left:-1px;top:9px;bottom:9px;width:2px;background:var(--signal)}.datum span{display:block;font:750 8px "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;color:var(--muted);letter-spacing:.15em;text-transform:uppercase}.datum strong{display:block;margin-top:7px;font:650 14px "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;overflow-wrap:anywhere}
.rail{border-left:1px solid var(--line);padding:20px 18px;overflow:auto;background:linear-gradient(180deg,rgba(7,12,28,.90),rgba(12,17,35,.78));box-shadow:inset 18px 0 40px rgba(1,4,18,.16)}.rail-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}.rail h2{margin:0;font:800 12px "Arial Narrow","Avenir Next Condensed",sans-serif;letter-spacing:.17em;text-transform:uppercase}.rail-tag{padding:4px 7px;border:1px solid rgba(115,167,255,.25);color:var(--telemetry);font:750 8px "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;letter-spacing:.14em}.route{--route-color:var(--signal);position:relative;padding:0 0 20px 29px}.route[data-status="estimated"]{--route-color:var(--reentry)}.route[data-status="checked"]{--route-color:var(--telemetry)}.route[data-status="refused"],.route[data-status="indeterminate"]{--route-color:var(--danger)}.route:before{content:"";position:absolute;left:6px;top:3px;width:9px;height:9px;border:2px solid var(--route-color);background:var(--void);box-shadow:0 0 0 4px color-mix(in srgb,var(--route-color) 12%,transparent)}.route:after{content:"";position:absolute;left:10px;top:17px;bottom:1px;width:1px;background:linear-gradient(var(--route-color),rgba(115,167,255,.13))}.route:last-child:after{display:none}.route strong{display:block;font:750 10px "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;color:var(--route-color);letter-spacing:.07em}.route span{display:block;margin-top:6px;font-size:11px;line-height:1.48;color:var(--muted);overflow-wrap:anywhere}
.sensor{margin-top:6px;padding:14px;border:1px solid rgba(246,199,110,.30);background:linear-gradient(145deg,rgba(246,199,110,.075),rgba(255,122,102,.025));box-shadow:inset 0 1px rgba(255,255,255,.025)}.sensor-title{display:flex;align-items:center;justify-content:space-between;margin-bottom:11px}.sensor-title strong{font:750 11px "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;letter-spacing:.04em}.sensor-title span{color:var(--amber);font:750 8px "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;letter-spacing:.12em}.sensor-head{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:end}.baud-wrap{display:grid;gap:5px}.baud-wrap span{font:700 8px "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;color:var(--muted);letter-spacing:.13em;text-transform:uppercase}.sensor button{height:36px;border:1px solid var(--amber);background:rgba(246,199,110,.07);color:var(--amber);padding:7px 12px;cursor:pointer;transition:background-color .15s ease,color .15s ease}.sensor button:hover{background:var(--amber);color:var(--void)}.sensor button:disabled{opacity:.55;cursor:wait}.sensor input{width:100%;min-width:0;height:36px;border:1px solid var(--line);background:rgba(4,8,21,.72);color:var(--frost);padding:7px 9px}.sensor-log{margin-top:11px;padding-top:10px;border-top:1px solid rgba(246,199,110,.16);max-height:110px;overflow:auto;font:10px/1.5 "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;color:var(--muted);white-space:pre-wrap}
.foot{display:flex;justify-content:space-between;gap:18px;padding:12px 24px;border-top:1px solid var(--line);background:rgba(8,11,26,.82);font:9px "IBM Plex Mono","JetBrains Mono","SFMono-Regular",monospace;color:var(--muted);letter-spacing:.06em}.foot b{color:var(--amber)}
.empty{height:100%;display:grid;place-items:center;text-align:center;padding:40px;color:var(--muted)}
.trace-path{stroke-dasharray:1;stroke-dashoffset:0}.cursor-line,.cursor-cross,.cursor-dot,.cursor-halo{pointer-events:none}
@media(max-width:1100px){.deck{grid-template-columns:minmax(0,1fr) 284px}.graph-wrap{grid-template-columns:minmax(0,1fr) 210px}.work{padding:16px}}
@media(max-width:900px){.mast{grid-template-columns:auto minmax(0,1fr) auto}.brand{min-width:0}.expression{grid-column:1/-1;grid-row:2}.deck{grid-template-columns:1fr}.rail{border-left:0;border-top:1px solid var(--line)}.work{grid-template-rows:540px auto}.graph-wrap{grid-template-columns:1fr;grid-template-rows:minmax(330px,1fr) 176px}.table-wrap{border-left:0;border-top:1px solid var(--line)}.lower{grid-template-columns:1fr}.rail{display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:18px}.rail-head{grid-column:1/-1;margin-bottom:0}.sensor{margin-top:0}.foot{align-items:flex-start}}
@media(max-width:620px){.mast{padding:14px 15px;gap:12px}.mark{width:38px;height:38px}.brand strong{font-size:13px}.brand span{font-size:8px}.status-chip{padding:7px;font-size:8px}.expression{grid-template-columns:1fr;gap:5px}.work{padding:10px;gap:10px;grid-template-rows:510px auto}.lower{gap:10px}.graph-wrap{grid-template-rows:minmax(300px,1fr) 176px}.rail{padding:16px 13px;grid-template-columns:1fr}.rail-head{grid-column:auto}.cursor-card{grid-template-columns:1fr}.foot{padding:11px 15px;display:grid}}
@media(prefers-reduced-motion:no-preference){.trace-path{animation:trace-on .7s cubic-bezier(.2,.8,.2,1)}.panel{animation:panel-in .34s ease-out both}.lower .panel:nth-child(2){animation-delay:.06s}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;transition:none!important;animation:none!important}}
@keyframes trace-on{from{stroke-dashoffset:1}}
@keyframes panel-in{from{opacity:.72;transform:translateY(5px)}to{opacity:1;transform:none}}
</style>
</head>
<body>
<main class="shell">
  <header class="mast">
    <div class="mark" aria-hidden="true">J</div>
    <div class="brand"><strong>JACKAL / THOTH</strong><span>LINKED EVIDENCE WORKSPACE</span></div>
    <div class="expression"><span class="expression-label">Active model</span><code id="expr">No delegated expression loaded</code></div>
    <div class="status-chip" id="status">checked view</div>
  </header>
  <section class="deck">
    <div class="work">
      <section class="panel">
        <div class="panel-title"><span>Graph + numeric table</span><em id="sample-label">delegated samples</em></div>
        <div class="graph-wrap">
          <svg id="plot" role="img" aria-label="Delegated JACKAL function samples"></svg>
          <div class="table-wrap"><table><thead><tr><th>#</th><th>x exact</th><th>y estimated</th></tr></thead><tbody id="rows"></tbody></table></div>
        </div>
      </section>
      <div class="lower">
        <section class="panel"><div class="panel-title"><span>Symbolic view</span><em>status preserved</em></div><div class="readout"><div class="equation" id="canonical">—</div><div class="subtle" id="derivative">—</div></div></section>
        <section class="panel"><div class="panel-title"><span>Linked inspector</span><em>one cursor</em></div><div class="readout"><div class="cursor-card"><div class="datum"><span>x / exact</span><strong id="cursor-x">—</strong></div><div class="datum"><span>f(x) / estimated</span><strong id="cursor-y">—</strong></div></div><div class="subtle" id="cursor-note">Move across the plot or focus a table row.</div></div></section>
      </div>
    </div>
    <aside class="rail">
      <div class="rail-head"><h2>Epistemic route</h2><span class="rail-tag">TRACE</span></div>
      <div id="route"></div>
      <section class="sensor">
        <div class="sensor-title"><strong>Local sensor dock</strong><span>DEVICE / RAW</span></div>
        <div class="sensor-head"><label class="baud-wrap"><span>Baud rate</span><input id="baud" value="9600" inputmode="numeric" aria-label="Baud rate"></label><button id="connect">Connect</button></div>
        <div class="sensor-log" id="sensor-log">Web Serial is optional. Raw device lines stay local; export them to jackal_sensor for evidence-aware ingestion.</div>
      </section>
    </aside>
  </section>
  <footer class="foot"><span>''' + html.escape(shell_note) + r'''</span><span><b>Pixels are not proof.</b> Use exact or bounded lanes for conclusions.</span></footer>
</main>
<script id="workspace-data" type="application/json">''' + data + r'''</script>
<script>
(()=>{
  'use strict';
  const data=JSON.parse(document.getElementById('workspace-data').textContent);
  const points=Array.isArray(data.points)?data.points:[];
  const exactNumber=v=>{const s=String(v);if(s.includes('/')){const [a,b]=s.split('/');return Number(a)/Number(b)}return Number(s)};
  const finite=points.map((p,i)=>({...p,i,xn:exactNumber(p.x),yn:Number(p.y)})).filter(p=>p.status==='estimated'&&Number.isFinite(p.xn)&&Number.isFinite(p.yn));
  document.getElementById('expr').textContent=data.expression?`f(x) = ${data.expression}`:'No delegated expression loaded';
  const status=document.getElementById('status');status.textContent=data.status||'checked view';status.dataset.status=String(data.status||'checked').toLowerCase();
  document.getElementById('sample-label').textContent=`${data.finite_sample_count||'0'} finite / ${points.length} requested`;
  document.getElementById('canonical').textContent=data.canonical_text||'Canonical view unavailable';
  document.getElementById('derivative').textContent=data.derivative_text||'Derivative view unavailable or refused';
  const tbody=document.getElementById('rows');
  points.forEach((p,i)=>{const tr=document.createElement('tr');tr.tabIndex=0;tr.dataset.index=String(i);if(p.status!=='estimated')tr.className='refused';tr.innerHTML=`<td>${i}</td><td></td><td></td>`;tr.children[1].textContent=p.x;tr.children[2].textContent=p.y||p.reason||p.status;tr.addEventListener('mouseenter',()=>select(i));tr.addEventListener('focus',()=>select(i));tbody.appendChild(tr)});
  const route=document.getElementById('route');
  (data.route||[]).forEach(item=>{const div=document.createElement('div');div.className='route';div.dataset.status=String(item.status||'unknown').toLowerCase();const strong=document.createElement('strong');strong.textContent=`${item.status||'unknown'} · ${item.tool||'view'}`;const span=document.createElement('span');span.textContent=item.parsed||item.detail||'Delegated result';div.append(strong,span);route.appendChild(div)});
  if(!route.children.length){route.innerHTML='<div class="route"><strong>EMPTY SHELL</strong><span>Call jackal_linked_workspace to load delegated evidence.</span></div>'}
  const svg=document.getElementById('plot'),NS='http://www.w3.org/2000/svg';let cursor=null,cross=null,dot=null,halo=null;
  const make=(name,attrs={})=>{const el=document.createElementNS(NS,name);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,String(v)));return el};
  function draw(){
    svg.replaceChildren();
    const box=svg.getBoundingClientRect(),w=Math.max(320,box.width),h=Math.max(260,box.height);
    svg.setAttribute('viewBox',`0 0 ${w} ${h}`);
    if(finite.length<2){
      const t=make('text',{x:w/2,y:h/2,fill:'#86a3b1','text-anchor':'middle'});
      t.textContent='No finite delegated curve available';svg.append(t);return;
    }
    const pad={l:62,r:22,t:24,b:46},fmt=value=>{
      if(!Number.isFinite(value))return '—';
      const absolute=Math.abs(value);
      return absolute!==0&&(absolute>=10000||absolute<.001)
        ?value.toExponential(2):String(Number(value.toPrecision(5)));
    };
    let xmin=Math.min(...finite.map(p=>p.xn)),xmax=Math.max(...finite.map(p=>p.xn));
    let ymin=Math.min(...finite.map(p=>p.yn)),ymax=Math.max(...finite.map(p=>p.yn));
    if(xmin===xmax){xmin-=1;xmax+=1}
    if(ymin===ymax){const d=Math.max(1,Math.abs(ymin)*.05);ymin-=d;ymax+=d}
    const yp=(ymax-ymin)*.06;ymin-=yp;ymax+=yp;
    const sx=x=>pad.l+(x-xmin)/(xmax-xmin)*(w-pad.l-pad.r);
    const sy=y=>h-pad.b-(y-ymin)/(ymax-ymin)*(h-pad.t-pad.b);
    const defs=make('defs');
    const fill=make('linearGradient',{id:'trace-fill',x1:'0',x2:'0',y1:'0',y2:'1'});
    fill.append(make('stop',{offset:'0%','stop-color':'#73a7ff','stop-opacity':'.24'}),make('stop',{offset:'68%','stop-color':'#5de7ca','stop-opacity':'.07'}),make('stop',{offset:'100%','stop-color':'#5de7ca','stop-opacity':'0'}));
    defs.append(fill);svg.append(defs);
    svg.append(make('rect',{x:pad.l,y:pad.t,width:w-pad.l-pad.r,height:h-pad.t-pad.b,fill:'none',stroke:'rgba(115,167,255,.13)'}));
    for(let i=0;i<=8;i++){
      const ratio=i/8,x=pad.l+ratio*(w-pad.l-pad.r),value=xmin+ratio*(xmax-xmin);
      svg.append(make('line',{x1:x,x2:x,y1:pad.t,y2:h-pad.b,stroke:i%2===0?'rgba(145,164,196,.17)':'rgba(145,164,196,.075)'}));
      if(i%2===0){const label=make('text',{x,y:h-17,fill:'#8195b7','text-anchor':'middle','font-size':10,'font-family':'monospace'});label.textContent=fmt(value);svg.append(label)}
    }
    for(let i=0;i<=6;i++){
      const ratio=i/6,y=pad.t+ratio*(h-pad.t-pad.b),value=ymax-ratio*(ymax-ymin);
      svg.append(make('line',{x1:pad.l,x2:w-pad.r,y1:y,y2:y,stroke:i%2===0?'rgba(145,164,196,.17)':'rgba(145,164,196,.075)'}));
      if(i%2===0){const label=make('text',{x:pad.l-9,y:y+3,fill:'#8195b7','text-anchor':'end','font-size':10,'font-family':'monospace'});label.textContent=fmt(value);svg.append(label)}
    }
    if(xmin<=0&&xmax>=0)svg.append(make('line',{x1:sx(0),x2:sx(0),y1:pad.t,y2:h-pad.b,stroke:'rgba(236,243,255,.33)','stroke-width':1.2}));
    if(ymin<=0&&ymax>=0)svg.append(make('line',{x1:pad.l,x2:w-pad.r,y1:sy(0),y2:sy(0),stroke:'rgba(236,243,255,.33)','stroke-width':1.2}));
    const xAxis=make('text',{x:w-pad.r,y:pad.t+15,fill:'#73a7ff','text-anchor':'end','font-size':8,'font-weight':700,'font-family':'monospace','letter-spacing':'.12em'});xAxis.textContent='X / EXACT';svg.append(xAxis);
    const yAxis=make('text',{x:pad.l+8,y:pad.t+15,fill:'#ff7a66','font-size':8,'font-weight':700,'font-family':'monospace','letter-spacing':'.12em'});yAxis.textContent='F(X) / ESTIMATED';svg.append(yAxis);
    const groups=[];let active=[];
    finite.forEach((p,i)=>{if(i&&p.i!==finite[i-1].i+1){groups.push(active);active=[]}active.push(p)});
    if(active.length)groups.push(active);
    groups.forEach(group=>{
      if(group.length<2)return;
      const path=group.map((p,i)=>`${i?'L':'M'}${sx(p.xn)},${sy(p.yn)}`).join(' ');
      const base=ymin<=0&&ymax>=0?sy(0):h-pad.b;
      const area=`${path} L${sx(group[group.length-1].xn)},${base} L${sx(group[0].xn)},${base} Z`;
      svg.append(make('path',{d:area,fill:'url(#trace-fill)',stroke:'none'}));
      svg.append(make('path',{d:path,fill:'none',stroke:'rgba(73,112,255,.28)','stroke-width':11,'stroke-linecap':'round','stroke-linejoin':'round'}));
      svg.append(make('path',{d:path,fill:'none',stroke:'#5de7ca','stroke-width':3.2,'stroke-linecap':'round','stroke-linejoin':'round',class:'trace-path',pathLength:1}));
      group.forEach(p=>svg.append(make('circle',{cx:sx(p.xn),cy:sy(p.yn),r:3,fill:'#080b1a',stroke:'#73a7ff','stroke-width':1.6})));
    });
    cursor=make('line',{x1:0,x2:0,y1:pad.t,y2:h-pad.b,stroke:'#ff7a66','stroke-width':1,'stroke-dasharray':'4 5',class:'cursor-line'});
    cross=make('line',{x1:pad.l,x2:w-pad.r,y1:0,y2:0,stroke:'rgba(255,122,102,.55)','stroke-width':1,'stroke-dasharray':'2 7',class:'cursor-cross'});
    halo=make('circle',{cx:0,cy:0,r:11,fill:'rgba(255,122,102,.10)',stroke:'rgba(255,122,102,.34)','stroke-width':1,class:'cursor-halo'});
    dot=make('circle',{cx:0,cy:0,r:5,fill:'#ff7a66',stroke:'#080b1a','stroke-width':2,class:'cursor-dot'});
    svg.append(cursor,cross,halo,dot);
    svg.onpointermove=event=>{
      const rect=svg.getBoundingClientRect(),mouse=(event.clientX-rect.left)/rect.width*w;
      let best=finite[0],distance=Infinity;
      finite.forEach(point=>{const candidate=Math.abs(sx(point.xn)-mouse);if(candidate<distance){best=point;distance=candidate}});
      select(best.i);
    };
    svg._map={sx,sy};select(finite[0].i);
  }
  function select(index){const p=points[index];if(!p)return;tbody.querySelectorAll('tr').forEach((tr,i)=>tr.classList.toggle('active',i===index));document.getElementById('cursor-x').textContent=p.x||'—';document.getElementById('cursor-y').textContent=p.y||p.reason||p.status||'—';document.getElementById('cursor-note').textContent=`sample ${index} · ${p.status||'unknown'} · table, plot, and inspector linked`;const q=finite.find(v=>v.i===index);if(q&&svg._map&&cursor&&cross&&dot&&halo){const x=svg._map.sx(q.xn),y=svg._map.sy(q.yn);cursor.setAttribute('x1',x);cursor.setAttribute('x2',x);cross.setAttribute('y1',y);cross.setAttribute('y2',y);dot.setAttribute('cx',x);dot.setAttribute('cy',y);halo.setAttribute('cx',x);halo.setAttribute('cy',y)}}
  addEventListener('resize',draw,{passive:true});draw();
  const log=document.getElementById('sensor-log'),button=document.getElementById('connect');
  button.addEventListener('click',async()=>{if(!('serial'in navigator)){log.textContent='Web Serial is unavailable in this host. Supply exported device samples to jackal_sensor.';return}try{const port=await navigator.serial.requestPort();const baud=Number(document.getElementById('baud').value);if(!Number.isInteger(baud)||baud<=0)throw new Error('Baud rate must be a positive integer');await port.open({baudRate:baud});button.disabled=true;button.textContent='Reading';const decoder=new TextDecoderStream();port.readable.pipeTo(decoder.writable).catch(()=>{});const reader=decoder.readable.getReader();let pending='',lines=[];for(;;){const {value,done}=await reader.read();if(done)break;pending+=value;const split=pending.split(/\r?\n/);pending=split.pop()||'';for(const line of split){if(line.trim()){lines.push(line.trim());if(lines.length>200)lines.shift();log.textContent=lines.join('\n')}}}}catch(error){log.textContent=`Sensor acquisition stopped: ${error&&error.message?error.message:'unknown browser refusal'}. No provenance upgrade was minted.`}finally{button.disabled=false;button.textContent='Connect'}});
})();
</script>
</body>
</html>'''
    if len(document.encode("utf-8")) > MAX_RESOURCE_TEXT_BYTES:
        raise Refusal("resource-budget", "linked workspace HTML exceeds the resource budget")
    return document


def workspace_shell() -> str:
    return _workspace_document(
        {
            "status": "checked",
            "expression": "",
            "points": [],
            "finite_sample_count": "0",
            "canonical_text": "",
            "derivative_text": "",
            "route": [],
        },
        shell=True,
    )


def _workspace_tool(arguments: dict) -> dict:
    expression = arguments.get("expression")
    if (
        not isinstance(expression, str)
        or not expression
        or len(expression.encode("utf-8")) > MAX_EXPRESSION_BYTES
        or any(ord(character) < 32 for character in expression)
    ):
        raise Refusal("args", "expression must be nonempty bounded printable text")
    lower = _token(arguments.get("x_min"), "x_min")
    upper = _token(arguments.get("x_max"), "x_max")
    if _compare(lower, upper) >= 0:
        raise Refusal("interval-order", "x_min must be strictly below x_max")
    samples_text, samples = _integer(
        arguments.get("samples"), "samples", maximum=MAX_WORKSPACE_SAMPLES
    )
    if samples < MIN_WORKSPACE_SAMPLES:
        raise Refusal("sample-budget", "workspace sample count is below the admitted minimum")

    canonical = _kernel_call("jackal_canon", {"expression": expression}, allow_refusal=True)
    derivative = _kernel_call("jackal_diff", {"expression": expression}, allow_refusal=True)
    points: list[dict[str, str]] = []
    finite_count = 0
    for index in range(samples):
        coordinate = _exact(
            f"({lower})+({index})*(({upper})-({lower}))/(({samples_text})-1)"
        )
        substituted = X_TOKEN.sub(f"({coordinate})", expression)
        evaluated = _kernel_call(
            "jackal_evaluate", {"expression": substituted}, allow_refusal=True
        )
        rendered = evaluated.get("engine_output")
        if evaluated.get("status") != "estimated" or not isinstance(rendered, str):
            points.append(
                {
                    "x": coordinate,
                    "status": "refused" if evaluated.get("status") == "refused" else "indeterminate",
                    "reason": str(evaluated.get("reason", "no finite delegated value")),
                }
            )
            continue
        try:
            visual_value = decimal.Decimal(rendered)
        except decimal.InvalidOperation:
            visual_value = decimal.Decimal("NaN")
        if not visual_value.is_finite():
            points.append({"x": coordinate, "status": "indeterminate", "reason": "non-finite"})
            continue
        finite_count += 1
        points.append({"x": coordinate, "y": rendered, "status": "estimated"})

    canonical_text = canonical.get("engine_output")
    derivative_text = derivative.get("engine_output")
    route: list[dict[str, str]] = []
    for item in _TRACE:
        route.append(
            {
                "tool": str(item.get("tool", "unknown")),
                "status": str(item.get("status", "unknown")),
                "parsed": str(item.get("parsed", item.get("engine_output", "delegated call")))[:280],
            }
        )
    finite_count_exact = _count_exact(finite_count)
    payload = {
        "status": "estimated",
        "expression": expression,
        "points": points,
        "finite_sample_count": finite_count_exact,
        "canonical_text": canonical_text if isinstance(canonical_text, str) else "Canonical view refused",
        "derivative_text": derivative_text if isinstance(derivative_text, str) else "Derivative view refused",
        "route": route,
    }
    resource_text = _workspace_document(payload)
    resource_digest = hashlib.sha256(resource_text.encode("utf-8")).hexdigest()
    summary = (
        "JACKAL linked evidence workspace: symbolic, numeric, graph, table, sensor dock, "
        "and evidence-route views synchronized over delegated results. Pixels are not proof."
    )
    return {
        "status": "checked",
        "lane": "linked-evidence-workspace-v1",
        "formal": False,
        "consequence_ceiling": CONSEQUENCE_CEILING,
        "parsed": {
            "expression": expression,
            "x_interval": [lower, upper],
            "samples": samples_text,
        },
        "fields": {
            "points": points,
            "finite_sample_count": finite_count_exact,
            "canonical_result": canonical,
            "derivative_result": derivative,
            "resource_uri": f"ui://jackal/linked-workspace/{resource_digest}",
            "resource_sha256": resource_digest,
            "resource_mime_type": "text/html",
        },
        "field_status": {
            "points.x": "exact",
            "points.y": "estimated",
            "canonical_result": str(canonical.get("status", "indeterminate")),
            "derivative_result": str(derivative.get("status", "indeterminate")),
            "resource_sha256": "checked",
        },
        "delegated_to": list(_TRACE),
        "identities": {"jackal_stem_sha256": _identity()},
        "non_claims": [
            "The linked workspace is a presentation artifact and adds no assurance to any delegated result",
            "SVG geometry, graph pixels, line segments, hover selection, table ordering, and browser sensor display are not evidence",
            "Sampling cannot prove continuity, roots, extrema, absence of poles, or behavior between samples",
            "The browser sensor dock does not mint observed or measured provenance; export data through jackal_sensor with its source metadata",
        ],
        "_mcp_content": [
            {"type": "text", "text": summary},
            {
                "type": "resource",
                "resource": {
                    "uri": f"ui://jackal/linked-workspace/{resource_digest}",
                    "mimeType": "text/html",
                    "text": resource_text,
                },
            },
        ],
    }


def dispatch_integrated(
    name: str,
    arguments: dict,
    kernel_call: Callable[[str, dict], dict],
    identity: str,
) -> dict:
    global _KERNEL, _IDENTITY, _TRACE
    if name not in STEM_TOOL_NAMES or not isinstance(arguments, dict):
        return {
            "status": "refused",
            "reason": "tool-unknown",
            "detail": "STEM tool name or arguments are invalid",
        }

    class Kernel:
        @staticmethod
        def call(tool: str, delegated_arguments: dict) -> dict:
            return kernel_call(tool, delegated_arguments)

    _KERNEL = Kernel()
    _IDENTITY = identity
    _TRACE = []
    try:
        if name == "jackal_matrix":
            return _matrix_tool(arguments)
        if name == "jackal_regression":
            return _regression_tool(arguments)
        if name == "jackal_probability":
            return _probability_tool(arguments)
        if name == "jackal_hypothesis":
            return _hypothesis_tool(arguments)
        if name == "jackal_sensor":
            return _sensor_tool(arguments)
        if name == "jackal_aerospace":
            return _aerospace_tool(arguments)
        return _workspace_tool(arguments)
    except Refusal as error:
        return _refusal(error.reason, error.detail)
    except Exception:
        return _refusal("stem-error", "STEM orchestration failed closed")
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


def _numeric_array(description: str) -> dict:
    return {
        "type": "array",
        "items": {"type": "string"},
        "description": description,
    }


def tool_definitions() -> list[dict]:
    matrix_schema = {
        "type": "array",
        "items": {"type": "array", "items": {"type": "string"}},
        "description": "Rectangular array of exact integer, decimal, scientific, or rational tokens.",
    }
    return [
        _definition(
            "jackal_matrix",
            "JACKAL exact matrices",
            "Exact-rational matrix addition, multiplication, transpose, determinant, RREF, inverse, and linear solve. Every reported numeric cell delegates to jackal_exact; orchestration is identity-pinned and tested, not formal-bounded.",
            _schema(
                {
                    "operation": {"type": "string", "enum": ["add", "determinant", "inverse", "multiply", "rref", "solve", "transpose"]},
                    "matrix": matrix_schema,
                    "second_matrix": matrix_schema,
                    "vector": _numeric_array("Right-hand-side vector for solve."),
                },
                ["operation", "matrix"],
            ),
        ),
        _definition(
            "jackal_regression",
            "JACKAL exact-field regression",
            "Polynomial ordinary-least-squares regression with exact-rational normal equations, coefficients, fitted values, SSE, SST, and R-squared. Top-level status is model-based because exact fitting does not validate the model.",
            _schema(
                {
                    "model": {"type": "string", "enum": ["polynomial_ols"]},
                    "degree": {"type": "string", "description": "Canonical polynomial degree within the tool budget."},
                    "x": _numeric_array("Exact-rational predictor values."),
                    "y": _numeric_array("Exact-rational response values."),
                },
                ["model", "degree", "x", "y"],
            ),
        ),
        _definition(
            "jackal_probability",
            "JACKAL probability models",
            "Exact binomial PMF/CDF fields or estimated finite-cutoff normal CDF integration. All outputs remain model-based and preserve distributional assumptions.",
            _schema(
                {
                    "operation": {"type": "string", "enum": ["binomial_pmf", "binomial_cdf", "normal_cdf"]},
                    "n": {"type": "string"},
                    "k": {"type": "string"},
                    "p": {"type": "string"},
                    "z": {"type": "string"},
                    "tail_cutoff": {"type": "string"},
                    "tolerance": {"type": "string"},
                },
                ["operation"],
            ),
        ),
        _definition(
            "jackal_hypothesis",
            "JACKAL hypothesis tests",
            "One-sample z testing with estimated finite-tail p-values or exact one-sided binomial tails. Returns model-based with test assumptions and never interprets a p-value as the probability a hypothesis is true.",
            _schema(
                {
                    "operation": {"type": "string", "enum": ["one_sample_z", "exact_binomial_tail"]},
                    "alternative": {"type": "string", "enum": ["less", "greater", "two_sided"]},
                    "sample_mean": {"type": "string"},
                    "null_mean": {"type": "string"},
                    "population_sd": {"type": "string"},
                    "n": {"type": "string"},
                    "k": {"type": "string"},
                    "p0": {"type": "string"},
                    "tail_cutoff": {"type": "string"},
                    "tolerance": {"type": "string"},
                },
                ["operation", "alternative"],
            ),
        ),
        _definition(
            "jackal_sensor",
            "JACKAL sensor data",
            "Ingest a caller-supplied sensor batch or apply a declared exact linear calibration, preserving supplied provenance and returning exact descriptive fields plus a formal-bounded standard-deviation enclosure.",
            _schema(
                {
                    "operation": {"type": "string", "enum": ["ingest_batch", "linear_calibration"]},
                    "sensor_id": {"type": "string"},
                    "channel": {"type": "string"},
                    "quantity": {"type": "string"},
                    "unit": {"type": "string"},
                    "samples": _numeric_array("Raw caller-supplied sample tokens."),
                    "source": {"type": "string"},
                    "observed_at": {"type": "string"},
                    "scale": {"type": "string"},
                    "offset": {"type": "string"},
                    "calibration_source": {"type": "string"},
                    "calibration_as_of": {"type": "string"},
                },
                ["operation", "sensor_id", "channel", "quantity", "unit", "samples", "source", "observed_at"],
            ),
        ),
        _definition(
            "jackal_aerospace",
            "JACKAL aerospace models",
            "Claim-aware circular-orbit, vis-viva, rocket-equation, Hohmann-transfer, and plane-change workflows. Exact/formal scalar fields remain conditional on explicit physical-model assumptions and never inherit the published finite-burn certificate.",
            _schema(
                {
                    "operation": {"type": "string", "enum": ["circular_orbit", "vis_viva", "rocket_equation", "hohmann_transfer", "plane_change"]},
                    "parameters": {"type": "object", "description": "Named exact-rational parameters for the selected aerospace model."},
                },
                ["operation", "parameters"],
            ),
        ),
        _definition(
            "jackal_linked_workspace",
            "JACKAL linked evidence workspace",
            "Return a professional self-contained HTML workspace linking symbolic, numeric, graph, table, sensor-dock, and evidence-route views over delegated JACKAL results. The UI adds no assurance; pixels are not proof.",
            _schema(
                {
                    "expression": {"type": "string", "description": "JACKAL expression in plotting variable x."},
                    "x_min": {"type": "string", "description": "Exact-rational lower x bound."},
                    "x_max": {"type": "string", "description": "Exact-rational upper x bound."},
                    "samples": {"type": "string", "description": "Canonical bounded sample count."},
                },
                ["expression", "x_min", "x_max", "samples"],
            ),
        ),
    ]


if __name__ == "__main__":
    raise SystemExit("stem.py is an identity-pinned JACKAL module, not a standalone service")
