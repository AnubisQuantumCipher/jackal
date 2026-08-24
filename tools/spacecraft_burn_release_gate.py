#!/opt/homebrew/bin/python3
"""Fail closed on unqualified spacecraft assurance language."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Sequence


QUALIFIED_VERDICT = (
    "CERTIFIED SAFE under the stated finite-burn ODE model, supplied input bounds, "
    "and machine-checked interval-certificate assumptions"
)
QUALIFIED_PATTERN = re.compile(
    r"\s+".join(map(re.escape, QUALIFIED_VERDICT.split())), re.IGNORECASE
)
TARGETS = (
    Path("README.md"),
    Path("spacecraft_burn_cert/README.md"),
    Path("spacecraft_burn_cert/REPORT.md"),
    Path("plugins/jackel/skills/jackel/SKILL.md"),
)
FORBIDDEN = {
    "proved-safe": re.compile(r"\bPROVED\s+SAFE\b", re.IGNORECASE),
    "proved-unsafe": re.compile(r"\bPROVED\s+UNSAFE\b", re.IGNORECASE),
    "formally-proved-result": re.compile(r"\bformally\s+proved\b", re.IGNORECASE),
}


def scan(root: Path) -> dict:
    findings = []
    for relative in TARGETS:
        path = root / relative
        if not path.is_file():
            findings.append({"file": str(relative), "reason": "missing-publication-surface"})
            continue
        text = path.read_text(encoding="utf-8")
        for reason, pattern in FORBIDDEN.items():
            for match in pattern.finditer(text):
                findings.append({
                    "file": str(relative), "line": text.count("\n", 0, match.start()) + 1,
                    "reason": reason,
                })
        stripped = QUALIFIED_PATTERN.sub(
            lambda match: "".join("\n" if char == "\n" else " " for char in match.group(0)),
            text,
        )
        for match in re.finditer(r"CERTIFIED\s+SAFE", stripped, re.IGNORECASE):
            findings.append({
                "file": str(relative), "line": text.count("\n", 0, match.start()) + 1,
                "reason": "unqualified-certified-safe",
            })
    return {
        "status": "PASS" if not findings else "FAIL",
        "surface_count": len(TARGETS),
        "forbidden_current_surface_count": len(findings),
        "findings": findings,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    result = scan(args.root.resolve())
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
