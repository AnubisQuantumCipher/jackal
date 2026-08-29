#!/usr/bin/python3 -I -B
"""Reject SPARK proof assumptions without runner-image tool dependencies."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path


REPORT_ASSUME = re.compile(r"\(([1-9][0-9]*) pragma Assume statements?\)")
ADA_SUFFIXES = {".adb", ".ads"}
FORBIDDEN_PRAGMAS = {"annotate", "assume"}


def refuse(message: str) -> None:
    raise SystemExit(f"refused: {message}")


def identifiers(text: str) -> Iterator[tuple[str, int]]:
    """Yield Ada identifiers outside line comments and string literals."""

    index = 0
    line = 1
    while index < len(text):
        if text.startswith("--", index):
            newline = text.find("\n", index + 2)
            if newline < 0:
                return
            index = newline
            continue

        character = text[index]
        if character == '"':
            index += 1
            while index < len(text):
                if text[index] == '"':
                    if index + 1 < len(text) and text[index + 1] == '"':
                        index += 2
                        continue
                    index += 1
                    break
                if text[index] == "\n":
                    line += 1
                index += 1
            continue

        if character.isascii() and character.isalpha():
            start = index
            start_line = line
            index += 1
            while index < len(text):
                character = text[index]
                if not (
                    character.isascii()
                    and (character.isalnum() or character == "_")
                ):
                    break
                index += 1
            yield text[start:index].lower(), start_line
            continue

        if character == "\n":
            line += 1
        index += 1


def source_files(raw_roots: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for raw_root in raw_roots:
        root = Path(raw_root)
        if root.is_symlink() or not root.exists():
            refuse(f"SPARK source root is missing or symbolic: {root}")
        candidates = [root] if root.is_file() else root.rglob("*")
        for candidate in candidates:
            if candidate.suffix.lower() not in ADA_SUFFIXES:
                continue
            if candidate.is_symlink() or not candidate.is_file():
                refuse(f"SPARK source is not a regular file: {candidate}")
            resolved = candidate.resolve()
            if resolved not in seen:
                files.append(candidate)
                seen.add(resolved)
    if not files:
        refuse("no SPARK source files were found")
    return files


def check_source(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        refuse(f"cannot read SPARK source {path}: {error}")

    expect_pragma_name_at: int | None = None
    for identifier, line in identifiers(text):
        if expect_pragma_name_at is not None:
            if identifier in FORBIDDEN_PRAGMAS:
                refuse(
                    f"proof assumption or justification in {path}:"
                    f"{expect_pragma_name_at} ({identifier})"
                )
            expect_pragma_name_at = None
        if identifier == "pragma":
            expect_pragma_name_at = line


def main(arguments: list[str]) -> None:
    if len(arguments) < 2:
        refuse("a GNATprove report and SPARK source roots are required")

    report = Path(arguments[0])
    if report.is_symlink() or not report.is_file():
        refuse("the GNATprove report is not a regular file")
    try:
        report_text = report.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        refuse(f"cannot read the GNATprove report: {error}")
    if REPORT_ASSUME.search(report_text):
        refuse("GNATprove reports one or more proof assumptions")

    for path in source_files(arguments[1:]):
        check_source(path)


if __name__ == "__main__":
    main(sys.argv[1:])
