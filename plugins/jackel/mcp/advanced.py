#!/usr/bin/env python3 -B
"""Identity-pinned advanced CAS and graph tools on JACKAL's single MCP surface.

This module is not a second server and is not an arithmetic authority.  CAS
requests delegate to the sealed runtime.  Graph coordinates and function
values are recorded from delegated JACKAL calls; rasterization is explicitly a
visualization, never evidence.  The fixed HELLGATE result is installed only
after the independent exact-rational checker accepts its pinned certificate.
"""

from __future__ import annotations

import base64
import binascii
import copy
import decimal
import math
import re
import struct
import zlib
from fractions import Fraction
from typing import Callable


ADVANCED_TOOL_NAMES = frozenset(
    {"jackal_cas", "jackal_graph", "jackal_hellgate_ground_state"}
)
CONSEQUENCE_CEILING = "informational"
MAX_EXPRESSION_BYTES = 2048
MIN_GRAPH_SAMPLES = 17
MAX_GRAPH_SAMPLES = 257
GRAPH_WIDTH = 1200
GRAPH_HEIGHT = 720
GRAPH_SUPERSAMPLE = 2
RENDER_WIDTH = GRAPH_WIDTH * GRAPH_SUPERSAMPLE
RENDER_HEIGHT = GRAPH_HEIGHT * GRAPH_SUPERSAMPLE
X_TOKEN = re.compile(r"(?<![A-Za-z0-9_])x(?![A-Za-z0-9_])", re.ASCII)
CANONICAL_INTEGER = re.compile(r"(?:0|[1-9][0-9]*)\Z", re.ASCII)

CAS_ROUTES = {
    "exact": "jackal_exact",
    "evaluate": "jackal_evaluate",
    "canonicalize": "jackal_canon",
    "polynomial_canonicalize": "jackal_poly_canon",
    "polynomial_equal": "jackal_poly_eq",
    "polynomial_gcd": "jackal_poly_gcd",
    "rational_function_canonicalize": "jackal_ratfunc_canon",
    "real_roots_isolate": "jackal_roots_isolate",
    "algebraic_sign": "jackal_alg_sign",
    "algebraic_compare": "jackal_alg_cmp",
    "differentiate": "jackal_diff",
    "solve": "jackal_solve",
    "integrate": "jackal_integrate",
    "integrate_adaptive": "jackal_integrate_adaptive",
    "integrate_bounded": "jackal_integrate_bound",
    "integrate_formal": "jackal_integrate_bound_cert",
    "range_formal": "jackal_range_bound",
    "gaussian_integral_formal": "jackal_gaussian_integral",
    "sqrt_formal": "jackal_sqrt_rat_bound",
    "exp_formal": "jackal_exp_rat_bound",
    "ln_formal": "jackal_ln_rat_bound",
    "sin_formal": "jackal_sin_rat_bound",
    "cos_formal": "jackal_cos_rat_bound",
    "atan_formal": "jackal_atan_rat_bound",
    "tanh_formal": "jackal_tanh_rat_bound",
}


class Refusal(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


_KERNEL: object | None = None
_IDENTITY: str | None = None
_HELLGATE_RESULT: dict | None = None
_HELLGATE_IDENTITIES: dict[str, str] | None = None
_TRACE: list[dict] = []


def configure_hellgate(
    result: object,
    *,
    advanced_sha256: str,
    checker_sha256: str,
    certificate_sha256: str,
) -> None:
    global _HELLGATE_RESULT, _HELLGATE_IDENTITIES
    fields = result.get("fields") if isinstance(result, dict) else None
    trial = fields.get("trial_diagnostics") if isinstance(fields, dict) else None
    ground = fields.get("ground_state_transfer") if isinstance(fields, dict) else None
    if (
        not isinstance(result, dict)
        or result.get("status") != "bounded"
        or result.get("checker_verdict") != "ACCEPT"
        or result.get("formal") is not False
        or not isinstance(trial, dict)
        or trial.get("schema") != "jackal-hellgate-trial-diagnostics-v1"
        or trial.get("subject") != "normalized-certificate-trial-phi"
        or not isinstance(ground, dict)
        or ground.get("schema") != "jackal-hellgate-ground-transfer-v1"
        or ground.get("subject") != "positive-normalized-ground-state-u0"
        or not all(
            isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
            for value in (advanced_sha256, checker_sha256, certificate_sha256)
        )
    ):
        raise RuntimeError("HELLGATE certificate did not pass the startup gate")
    _HELLGATE_RESULT = copy.deepcopy(result)
    _HELLGATE_IDENTITIES = {
        "jackal_advanced_sha256": advanced_sha256,
        "hellgate_checker_sha256": checker_sha256,
        "hellgate_certificate_file_sha256": certificate_sha256,
    }


def _identity() -> str:
    if _IDENTITY is None:
        raise RuntimeError("advanced identity is unavailable outside integrated dispatch")
    return _IDENTITY


def _refusal(reason: str, detail: str) -> dict:
    return {
        "status": "refused",
        "reason": reason,
        "detail": detail,
        "consequence_ceiling": CONSEQUENCE_CEILING,
        "identities": {"jackal_advanced_sha256": _identity()},
        "non_claims": [
            "A refusal is an answer; no weaker lane was substituted",
            "No visual or numerical result was established",
        ],
    }


def _kernel_call(tool: str, arguments: dict) -> dict:
    if _KERNEL is None:
        raise Refusal("kernel-unavailable", "advanced module is not attached to JACKAL")
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
    if result.get("status") == "refused":
        raise Refusal(
            f"kernel-refused:{result.get('reason', 'unknown')}",
            str(result.get("detail", "the delegated JACKAL lane refused")),
        )
    return result


def _fraction(text: object, subject: str) -> Fraction:
    if not isinstance(text, str) or not text or len(text) > 256:
        raise Refusal("args", f"{subject} must be a bounded rational string")
    try:
        value = Fraction(text)
    except (ValueError, ZeroDivisionError) as error:
        raise Refusal("args", f"{subject} is not an integer, decimal, or rational") from error
    return value


def _cas(arguments: dict) -> dict:
    operation = arguments.get("operation")
    delegated_arguments = arguments.get("arguments")
    if not isinstance(operation, str) or operation not in CAS_ROUTES:
        raise Refusal("operation-unknown", "operation is not in the closed CAS route table")
    if not isinstance(delegated_arguments, dict):
        raise Refusal("args", "arguments must be an object for the selected JACKAL tool")
    tool = CAS_ROUTES[operation]
    result = _kernel_call(tool, delegated_arguments)
    return {
        "status": result.get("status", "indeterminate"),
        "lane": "cas-route",
        "formal": bool(result.get("formal", False)),
        "parsed": {"operation": operation, "delegated_tool": tool},
        "result": result,
        "delegated_to": list(_TRACE),
        "identities": {"jackal_advanced_sha256": _identity()},
        "non_claims": [
            "The CAS router adds no assurance to the delegated JACKAL result",
            "Preserve the delegated status, assumptions, identities, and non-claims unchanged",
        ],
    }


_FONT = {
    " ": "00000/00000/00000/00000/00000/00000/00000",
    "A": "01110/10001/10001/11111/10001/10001/10001",
    "B": "11110/10001/10001/11110/10001/10001/11110",
    "C": "01111/10000/10000/10000/10000/10000/01111",
    "D": "11110/10001/10001/10001/10001/10001/11110",
    "E": "11111/10000/10000/11110/10000/10000/11111",
    "F": "11111/10000/10000/11110/10000/10000/10000",
    "G": "01111/10000/10000/10111/10001/10001/01111",
    "H": "10001/10001/10001/11111/10001/10001/10001",
    "I": "11111/00100/00100/00100/00100/00100/11111",
    "J": "00111/00010/00010/00010/10010/10010/01100",
    "K": "10001/10010/10100/11000/10100/10010/10001",
    "L": "10000/10000/10000/10000/10000/10000/11111",
    "M": "10001/11011/10101/10101/10001/10001/10001",
    "N": "10001/11001/10101/10011/10001/10001/10001",
    "O": "01110/10001/10001/10001/10001/10001/01110",
    "P": "11110/10001/10001/11110/10000/10000/10000",
    "Q": "01110/10001/10001/10001/10101/10010/01101",
    "R": "11110/10001/10001/11110/10100/10010/10001",
    "S": "01111/10000/10000/01110/00001/00001/11110",
    "T": "11111/00100/00100/00100/00100/00100/00100",
    "U": "10001/10001/10001/10001/10001/10001/01110",
    "V": "10001/10001/10001/10001/10001/01010/00100",
    "W": "10001/10001/10001/10101/10101/10101/01010",
    "X": "10001/10001/01010/00100/01010/10001/10001",
    "Y": "10001/10001/01010/00100/00100/00100/00100",
    "Z": "11111/00001/00010/00100/01000/10000/11111",
    "0": "01110/10001/10011/10101/11001/10001/01110",
    "1": "00100/01100/00100/00100/00100/00100/01110",
    "2": "01110/10001/00001/00010/00100/01000/11111",
    "3": "11110/00001/00001/01110/00001/00001/11110",
    "4": "00010/00110/01010/10010/11111/00010/00010",
    "5": "11111/10000/10000/11110/00001/00001/11110",
    "6": "01110/10000/10000/11110/10001/10001/01110",
    "7": "11111/00001/00010/00100/01000/01000/01000",
    "8": "01110/10001/10001/01110/10001/10001/01110",
    "9": "01110/10001/10001/01111/00001/00001/01110",
    "+": "00000/00100/00100/11111/00100/00100/00000",
    "-": "00000/00000/00000/11111/00000/00000/00000",
    "*": "00000/10101/01110/11111/01110/10101/00000",
    "/": "00001/00010/00010/00100/01000/01000/10000",
    "^": "00100/01010/10001/00000/00000/00000/00000",
    "(": "00010/00100/01000/01000/01000/00100/00010",
    ")": "01000/00100/00010/00010/00010/00100/01000",
    "[": "01110/01000/01000/01000/01000/01000/01110",
    "]": "01110/00010/00010/00010/00010/00010/01110",
    ".": "00000/00000/00000/00000/00000/00110/00110",
    ",": "00000/00000/00000/00000/00110/00110/00100",
    ":": "00000/00110/00110/00000/00110/00110/00000",
    "=": "00000/00000/11111/00000/11111/00000/00000",
    "|": "00100/00100/00100/00100/00100/00100/00100",
    "_": "00000/00000/00000/00000/00000/00000/11111",
    "?": "01110/10001/00001/00010/00100/00000/00100",
}


def _set_pixel(buffer: bytearray, x: int, y: int, color: tuple[int, int, int]) -> None:
    if 0 <= x < RENDER_WIDTH and 0 <= y < RENDER_HEIGHT:
        offset = (y * RENDER_WIDTH + x) * 3
        buffer[offset : offset + 3] = bytes(color)


def _fill_rect(
    buffer: bytearray,
    left: int,
    top: int,
    right: int,
    bottom: int,
    color: tuple[int, int, int],
) -> None:
    clipped_left = max(0, left)
    clipped_top = max(0, top)
    clipped_right = min(RENDER_WIDTH, right)
    clipped_bottom = min(RENDER_HEIGHT, bottom)
    if clipped_left >= clipped_right or clipped_top >= clipped_bottom:
        return
    row = bytes(color) * (clipped_right - clipped_left)
    for y in range(clipped_top, clipped_bottom):
        start = (y * RENDER_WIDTH + clipped_left) * 3
        buffer[start : start + len(row)] = row


def _line(
    buffer: bytearray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
    thickness: int = 1,
) -> None:
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    error = dx + dy
    while True:
        for ox in range(-(thickness // 2), thickness // 2 + 1):
            for oy in range(-(thickness // 2), thickness // 2 + 1):
                _set_pixel(buffer, x0 + ox, y0 + oy, color)
        if x0 == x1 and y0 == y1:
            break
        doubled = 2 * error
        if doubled >= dy:
            error += dy
            x0 += sx
        if doubled <= dx:
            error += dx
            y0 += sy


def _draw_text(
    buffer: bytearray,
    x: int,
    y: int,
    value: str,
    color: tuple[int, int, int],
    scale: int,
    align: str = "left",
) -> None:
    rendered = str(value).upper()
    width = max(0, (len(rendered) * 6 - 1) * scale)
    if align == "center":
        x -= width // 2
    elif align == "right":
        x -= width
    for character in rendered:
        rows = _FONT.get(character, _FONT["?"]).split("/")
        for row_index, row in enumerate(rows):
            for column_index, bit in enumerate(row):
                if bit == "1":
                    _fill_rect(
                        buffer,
                        x + column_index * scale,
                        y + row_index * scale,
                        x + (column_index + 1) * scale,
                        y + (row_index + 1) * scale,
                        color,
                    )
        x += 6 * scale


def _fit_text(value: str, max_width: int, scale: int) -> str:
    capacity = max(1, (max_width // scale + 1) // 6)
    rendered = str(value).upper()
    if len(rendered) <= capacity:
        return rendered
    if capacity <= 3:
        return rendered[:capacity]
    return rendered[: capacity - 3] + "..."


def _format_tick(value: float) -> str:
    if abs(value) < 1e-12:
        value = 0.0
    return f"{value:.5g}".upper()


def _downsample(rows: bytearray) -> bytearray:
    output = bytearray(GRAPH_WIDTH * GRAPH_HEIGHT * 3)
    area = GRAPH_SUPERSAMPLE * GRAPH_SUPERSAMPLE
    for y in range(GRAPH_HEIGHT):
        for x in range(GRAPH_WIDTH):
            red = green = blue = 0
            for offset_y in range(GRAPH_SUPERSAMPLE):
                source_y = y * GRAPH_SUPERSAMPLE + offset_y
                for offset_x in range(GRAPH_SUPERSAMPLE):
                    source_x = x * GRAPH_SUPERSAMPLE + offset_x
                    source = (source_y * RENDER_WIDTH + source_x) * 3
                    red += rows[source]
                    green += rows[source + 1]
                    blue += rows[source + 2]
            target = (y * GRAPH_WIDTH + x) * 3
            output[target] = red // area
            output[target + 1] = green // area
            output[target + 2] = blue // area
    return output


def _png(rows: bytearray) -> bytes:
    scanlines = bytearray()
    stride = GRAPH_WIDTH * 3
    for row in range(GRAPH_HEIGHT):
        scanlines.append(0)
        start = row * stride
        scanlines.extend(rows[start : start + stride])

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", GRAPH_WIDTH, GRAPH_HEIGHT, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(
        b"IDAT", zlib.compress(bytes(scanlines), 9)
    ) + chunk(b"IEND", b"")


def _render_graph(
    expression: str,
    samples: int,
    numeric: list[tuple[int, float, float]],
    x_low: float,
    x_high: float,
    y_low: float,
    y_high: float,
) -> bytes:
    scale = GRAPH_SUPERSAMPLE
    background_top = (7, 12, 19)
    background_bottom = (11, 19, 29)
    pixels = bytearray()
    for y in range(RENDER_HEIGHT):
        fraction = y / max(1, RENDER_HEIGHT - 1)
        color = tuple(
            round(background_top[channel] * (1 - fraction)
                  + background_bottom[channel] * fraction)
            for channel in range(3)
        )
        pixels.extend(bytes(color) * RENDER_WIDTH)

    foreground = (225, 236, 241)
    secondary = (135, 158, 171)
    muted = (92, 117, 132)
    grid = (30, 48, 61)
    border = (53, 75, 89)
    plot_background = (10, 18, 27)
    axis = (109, 139, 156)
    teal = (0, 224, 184)
    teal_highlight = (123, 255, 226)
    teal_shadow = (0, 74, 72)
    badge_background = (10, 51, 51)

    plot_left = 112 * scale
    plot_right = 1144 * scale
    plot_top = 150 * scale
    plot_bottom = 592 * scale
    _fill_rect(pixels, plot_left, plot_top, plot_right + 1, plot_bottom + 1, plot_background)

    title_scale = 6
    text_scale = 4
    small_scale = 3
    _draw_text(pixels, 64 * scale, 27 * scale, "JACKAL + THOTH", teal_highlight, title_scale)
    _draw_text(
        pixels,
        64 * scale,
        66 * scale,
        "EVIDENCE-AWARE FUNCTION GRAPH",
        secondary,
        text_scale,
    )
    badge_text = "ESTIMATED VISUALIZATION"
    badge_left = 874 * scale
    badge_top = 29 * scale
    badge_right = 1144 * scale
    badge_bottom = 64 * scale
    _fill_rect(
        pixels,
        badge_left,
        badge_top,
        badge_right,
        badge_bottom,
        badge_background,
    )
    _line(pixels, badge_left, badge_top, badge_right, badge_top, teal, 2)
    _line(pixels, badge_left, badge_bottom, badge_right, badge_bottom, teal, 2)
    _draw_text(
        pixels,
        (badge_left + badge_right) // 2,
        41 * scale,
        badge_text,
        teal_highlight,
        small_scale,
        "center",
    )

    expression_text = _fit_text(
        "F(X) = " + expression,
        plot_right - plot_left,
        text_scale,
    )
    _draw_text(
        pixels,
        plot_left,
        116 * scale,
        expression_text,
        foreground,
        text_scale,
    )
    _draw_text(
        pixels,
        plot_right,
        118 * scale,
        f"{samples} DELEGATED SAMPLES",
        muted,
        small_scale,
        "right",
    )

    x_divisions = 8
    y_divisions = 6
    for division in range(x_divisions + 1):
        gx = plot_left + (plot_right - plot_left) * division // x_divisions
        _line(pixels, gx, plot_top, gx, plot_bottom, grid, 2)
        tick = x_low + (x_high - x_low) * division / x_divisions
        _draw_text(
            pixels,
            gx,
            609 * scale,
            _format_tick(tick),
            secondary,
            small_scale,
            "center",
        )
    for division in range(y_divisions + 1):
        gy = plot_top + (plot_bottom - plot_top) * division // y_divisions
        _line(pixels, plot_left, gy, plot_right, gy, grid, 2)
        tick = y_high - (y_high - y_low) * division / y_divisions
        _draw_text(
            pixels,
            98 * scale,
            gy - 3 * scale,
            _format_tick(tick),
            secondary,
            small_scale,
            "right",
        )

    _line(pixels, plot_left, plot_top, plot_right, plot_top, border, 2)
    _line(pixels, plot_right, plot_top, plot_right, plot_bottom, border, 2)
    _line(pixels, plot_right, plot_bottom, plot_left, plot_bottom, border, 2)
    _line(pixels, plot_left, plot_bottom, plot_left, plot_top, border, 2)

    def map_x(value: float) -> int:
        return round(
            plot_left
            + (value - x_low) * (plot_right - plot_left) / (x_high - x_low)
        )

    def map_y(value: float) -> int:
        return round(
            plot_bottom
            - (value - y_low) * (plot_bottom - plot_top) / (y_high - y_low)
        )

    if x_low <= 0 <= x_high:
        zero_x = map_x(0.0)
        _line(pixels, zero_x, plot_top, zero_x, plot_bottom, axis, 4)
    if y_low <= 0 <= y_high:
        zero_y = map_y(0.0)
        _line(pixels, plot_left, zero_y, plot_right, zero_y, axis, 4)

    previous: tuple[int, int, int] | None = None
    segments: list[tuple[int, int, int, int]] = []
    for sample_index, x_value, y_value in numeric:
        current = (map_x(x_value), map_y(y_value))
        if previous is not None and sample_index == previous[0] + 1:
            segments.append((previous[1], previous[2], current[0], current[1]))
        previous = (sample_index, current[0], current[1])
    for x0, y0, x1, y1 in segments:
        _line(pixels, x0, y0, x1, y1, teal_shadow, 12)
    for x0, y0, x1, y1 in segments:
        _line(pixels, x0, y0, x1, y1, teal, 6)
    for x0, y0, x1, y1 in segments:
        _line(pixels, x0, y0, x1, y1, teal_highlight, 2)

    footer = "EXACT RATIONAL X COORDINATES  |  ESTIMATED F64 Y SAMPLES  |  PIXELS ARE NOT PROOF"
    _draw_text(
        pixels,
        64 * scale,
        680 * scale,
        _fit_text(footer, 1080 * scale, small_scale),
        muted,
        small_scale,
    )
    return _png(_downsample(pixels))


def _graph(arguments: dict) -> dict:
    expression = arguments.get("expression")
    if (
        not isinstance(expression, str)
        or not expression
        or len(expression.encode("utf-8")) > MAX_EXPRESSION_BYTES
        or any(ord(character) < 32 for character in expression)
    ):
        raise Refusal("args", "expression must be nonempty bounded printable text")
    lower = _fraction(arguments.get("x_min"), "x_min")
    upper = _fraction(arguments.get("x_max"), "x_max")
    if lower >= upper:
        raise Refusal("interval-order", "x_min must be strictly below x_max")
    samples_text = arguments.get("samples")
    if not isinstance(samples_text, str) or CANONICAL_INTEGER.fullmatch(samples_text) is None:
        raise Refusal("args", "samples must be a canonical positive integer string")
    samples = int(samples_text)
    if not MIN_GRAPH_SAMPLES <= samples <= MAX_GRAPH_SAMPLES:
        raise Refusal(
            "sample-budget",
            f"samples must be between {MIN_GRAPH_SAMPLES} and {MAX_GRAPH_SAMPLES}",
        )

    points: list[dict[str, str]] = []
    numeric: list[tuple[int, float, float]] = []
    for index in range(samples):
        coordinate_result = _kernel_call(
            "jackal_exact",
            {
                "expression": (
                    f"({lower}) + ({index})*(({upper})-({lower}))/({samples - 1})"
                )
            },
        )
        fields = coordinate_result.get("fields")
        coordinate = fields.get("exact") if isinstance(fields, dict) else None
        if not isinstance(coordinate, str):
            raise Refusal("kernel-error", "jackal_exact returned no graph coordinate")
        substituted = X_TOKEN.sub(f"({coordinate})", expression)
        try:
            evaluated = _kernel_call("jackal_evaluate", {"expression": substituted})
        except Refusal as error:
            if error.reason.startswith("kernel-refused:"):
                points.append(
                    {"x": coordinate, "status": "refused", "reason": error.reason}
                )
                continue
            raise
        rendered = evaluated.get("engine_output")
        if not isinstance(rendered, str):
            points.append({"x": coordinate, "status": "indeterminate"})
            continue
        try:
            y_decimal = decimal.Decimal(rendered)
        except decimal.InvalidOperation:
            points.append({"x": coordinate, "status": "indeterminate"})
            continue
        if not y_decimal.is_finite():
            points.append({"x": coordinate, "status": "indeterminate"})
            continue
        try:
            x_float = float(Fraction(coordinate))
            y_float = float(y_decimal)
        except (OverflowError, ValueError):
            points.append({"x": coordinate, "status": "indeterminate"})
            continue
        if not math.isfinite(x_float) or not math.isfinite(y_float):
            points.append({"x": coordinate, "status": "indeterminate"})
            continue
        numeric.append((index, x_float, y_float))
        points.append({"x": coordinate, "y": rendered, "status": "estimated"})

    if len(numeric) < 2:
        raise Refusal("graph-empty", "fewer than two finite delegated samples were available")
    y_values = [point[2] for point in numeric]
    y_low = min(y_values)
    y_high = max(y_values)
    if y_low == y_high:
        padding = max(1.0, abs(y_low) * 0.05)
    else:
        padding = (y_high - y_low) * 0.05
    y_low -= padding
    y_high += padding
    x_low = float(lower)
    x_high = float(upper)
    image = _render_graph(
        expression,
        samples,
        numeric,
        x_low,
        x_high,
        y_low,
        y_high,
    )
    summary = (
        f"JACKAL graph: {expression} on [{lower}, {upper}] using {samples} delegated "
        "f64 samples. The curve is estimated visualization, not a bound or proof."
    )
    return {
        "status": "estimated",
        "lane": "graph-delegated-f64-v1",
        "formal": False,
        "consequence_ceiling": CONSEQUENCE_CEILING,
        "parsed": {
            "expression": expression,
            "x_interval": [str(lower), str(upper)],
            "samples": str(samples),
        },
        "fields": {
            "points": points,
            "finite_sample_count": len(numeric),
            "observed_y_min": str(min(y_values)),
            "observed_y_max": str(max(y_values)),
            "image_mime_type": "image/png",
        },
        "delegated_to": list(_TRACE),
        "identities": {"jackal_advanced_sha256": _identity()},
        "non_claims": [
            "Graph pixels and connecting line segments are visualization only",
            "Every plotted y value is status=estimated IEEE f64, not bounded or formal-bounded",
            "Refused or indeterminate samples break the rendered curve instead of being bridged",
            "Sampling cannot prove continuity, roots, extrema, absence of poles, or behavior between samples",
            "Use JACKAL's exact or bounded lanes separately for claims inferred from the graph",
        ],
        "_mcp_content": [
            {"type": "text", "text": summary},
            {
                "type": "image",
                "data": base64.b64encode(image).decode("ascii"),
                "mimeType": "image/png",
            },
        ],
    }


def _hellgate(arguments: dict) -> dict:
    if arguments.get("problem_id") != "hellgate-v1":
        raise Refusal(
            "unsupported-problem",
            "this certificate lane admits only problem_id='hellgate-v1'",
        )
    if _HELLGATE_RESULT is None or _HELLGATE_IDENTITIES is None:
        raise Refusal("certificate-unavailable", "HELLGATE startup verification is unavailable")
    result = copy.deepcopy(_HELLGATE_RESULT)
    identities = result.setdefault("identities", {})
    if not isinstance(identities, dict):
        raise Refusal("certificate-error", "verified result identities are malformed")
    identities.update(_HELLGATE_IDENTITIES)
    result["consequence_ceiling"] = "advisory"
    return result


def dispatch_integrated(
    name: str,
    arguments: dict,
    kernel_call: Callable[[str, dict], dict],
    identity: str,
) -> dict:
    global _KERNEL, _IDENTITY, _TRACE
    if name not in ADVANCED_TOOL_NAMES or not isinstance(arguments, dict):
        return {
            "status": "refused",
            "reason": "tool-unknown",
            "detail": "advanced tool name or arguments are invalid",
        }

    class Kernel:
        evaluator_sha256: str | None = None

        @staticmethod
        def call(tool: str, delegated_arguments: dict) -> dict:
            return kernel_call(tool, delegated_arguments)

    _KERNEL = Kernel()
    _IDENTITY = identity
    _TRACE = []
    try:
        if name == "jackal_cas":
            return _cas(arguments)
        if name == "jackal_graph":
            return _graph(arguments)
        return _hellgate(arguments)
    except Refusal as error:
        return _refusal(error.reason, error.detail)
    except Exception:
        return _refusal("advanced-error", "advanced orchestration failed closed")
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


def tool_definitions() -> list[dict]:
    return [
        _definition(
            "jackal_cas",
            "JACKAL unified CAS",
            "One evidence-preserving front door for exact, symbolic, numerical, bounded, and formal JACKAL lanes. The router adds no assurance and never silently downgrades.",
            _schema(
                {
                    "operation": {
                        "type": "string",
                        "enum": sorted(CAS_ROUTES),
                        "description": "Closed CAS operation identifier.",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments for the selected underlying JACKAL tool.",
                    },
                },
                ["operation", "arguments"],
            ),
        ),
        _definition(
            "jackal_graph",
            "JACKAL graph",
            "Render a PNG curve from exact rational x coordinates and delegated status=estimated JACKAL evaluations. Pixels are explicitly not proof; use a bound lane for graph-derived claims.",
            _schema(
                {
                    "expression": {
                        "type": "string",
                        "description": "JACKAL expression in the single plotting variable x.",
                    },
                    "x_min": {"type": "string", "description": "Rational lower x bound."},
                    "x_max": {"type": "string", "description": "Rational upper x bound."},
                    "samples": {
                        "type": "string",
                        "description": "Canonical integer sample count, 17..257.",
                    },
                },
                ["expression", "x_min", "x_max", "samples"],
            ),
        ),
        _definition(
            "jackal_hellgate_ground_state",
            "JACKAL HELLGATE ground-state certificate",
            "Replay the identity-pinned exact-rational nonlinear Barta certificate for the fixed HELLGATE positive even normalized ground-state eigenvalue, scoped trial diagnostics, and a strong-convexity transfer for the ground-state quartic norm and energy functional. Returns status=bounded, never formal-bounded; trial moments are not ground-state moments.",
            _schema(
                {
                    "problem_id": {
                        "type": "string",
                        "enum": ["hellgate-v1"],
                        "description": "Exact fixed problem identifier.",
                    }
                },
                ["problem_id"],
            ),
        ),
    ]


if __name__ == "__main__":
    raise SystemExit(
        "advanced.py is an identity-pinned JACKAL module, not a standalone service"
    )
