#!/usr/bin/env python3
"""Rendered acceptance for JACKAL's static linked evidence workspace."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from plugins.jackel.mcp import stem


def fixture_document() -> str:
    points = [
        {"x": "-4", "y": "12", "status": "estimated"},
        {"x": "-3", "y": "5", "status": "estimated"},
        {"x": "-2", "y": "0", "status": "estimated"},
        {"x": "-1", "y": "-3", "status": "estimated"},
        {"x": "0", "y": "-4", "status": "estimated"},
        {"x": "1", "y": "-3", "status": "estimated"},
        {"x": "2", "y": "0", "status": "estimated"},
        {"x": "3", "y": "5", "status": "estimated"},
        {"x": "4", "y": "12", "status": "estimated"},
    ]
    return stem._workspace_document(
        {
            "status": "checked",
            "expression": "x^2 - 4",
            "points": points,
            "finite_sample_count": "9",
            "canonical_text": "(sub (pow (var x) (num 2)) (num 4))",
            "derivative_text": "d/dx[x^2-4] = 2*x · status=checked",
            "route": [
                {"tool": "jackal_canon", "status": "exact", "parsed": "canonical expression"},
                {"tool": "jackal_diff", "status": "checked", "parsed": "sampled symbolic derivative check"},
                {"tool": "jackal_exact", "status": "exact", "parsed": "rational x coordinates"},
                {"tool": "jackal_evaluate", "status": "estimated", "parsed": "sampled y values"},
            ],
        }
    )


def run(output: Path, mobile_output: Path | None = None) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if mobile_output is not None:
        mobile_output.parent.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1440, "height": 980},
            device_scale_factor=1,
        )
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.set_content(fixture_document(), wait_until="networkidle")

        page.locator("#plot").wait_for(state="visible")
        if page.locator("#rows tr").count() != 9:
            raise RuntimeError("workspace table did not render every supplied fixture point")
        if page.locator(".route").count() != 4:
            raise RuntimeError("workspace evidence route did not render every fixture stage")
        if page.locator("#rows tr.active").count() != 1:
            raise RuntimeError("workspace did not establish one synchronized cursor")
        if page.locator('#status[data-status="checked"]').count() != 1:
            raise RuntimeError("workspace did not expose the result status visually")
        if page.locator(".trace-path").count() != 1:
            raise RuntimeError("workspace did not render the continuous delegated trace")
        if page.locator('path[fill="url(#trace-fill)"]').count() != 1:
            raise RuntimeError("workspace did not render the graph depth layer")
        route_statuses = page.locator(".route").evaluate_all(
            "nodes => nodes.map(node => node.dataset.status)"
        )
        if route_statuses != ["exact", "checked", "exact", "estimated"]:
            raise RuntimeError("workspace did not preserve route status classes")

        page.locator("#rows tr").nth(2).focus()
        if page.locator("#cursor-x").inner_text() != "-2":
            raise RuntimeError("keyboard table focus did not synchronize the inspector")

        plot = page.locator("#plot").bounding_box()
        if plot is None:
            raise RuntimeError("workspace plot has no rendered bounds")
        page.mouse.move(plot["x"] + plot["width"] - 8, plot["y"] + plot["height"] / 2)
        page.wait_for_timeout(100)
        if page.locator("#cursor-x").inner_text() != "4":
            raise RuntimeError("plot hover did not synchronize the table and inspector")
        page.evaluate("document.activeElement.blur()")

        page.screenshot(path=str(output), full_page=True)

        page.locator("#connect").click()
        page.wait_for_timeout(100)
        sensor_log = page.locator("#sensor-log").inner_text()
        if "unavailable" not in sensor_log and "stopped" not in sensor_log:
            raise RuntimeError("sensor dock did not expose its browser/device refusal")

        page.emulate_media(reduced_motion="reduce")
        trace_animation = page.locator(".trace-path").evaluate(
            "element => getComputedStyle(element).animationName"
        )
        if trace_animation != "none":
            raise RuntimeError("workspace did not honor reduced-motion preference")

        for width, height in ((760, 1100), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(100)
            horizontal_overflow = page.evaluate(
                "document.documentElement.scrollWidth > document.documentElement.clientWidth"
            )
            if horizontal_overflow:
                raise RuntimeError(
                    f"responsive workspace introduces horizontal overflow at {width}px"
                )
            if not page.locator("#status").is_visible() or not page.locator("#expr").is_visible():
                raise RuntimeError(
                    f"responsive workspace hides primary evidence context at {width}px"
                )
            mobile_plot = page.locator("#plot").bounding_box()
            if mobile_plot is None or mobile_plot["width"] <= 0 or mobile_plot["height"] <= 0:
                raise RuntimeError(f"responsive workspace collapsed the graph at {width}px")
            if width == 760 and mobile_output is not None:
                page.screenshot(path=str(mobile_output), full_page=True)
        browser.close()

    if console_errors or page_errors:
        raise RuntimeError(
            f"workspace emitted browser errors: console={console_errors!r} page={page_errors!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mobile-output", type=Path)
    arguments = parser.parse_args()
    run(arguments.output, arguments.mobile_output)
    print(arguments.output)
    if arguments.mobile_output is not None:
        print(arguments.mobile_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
