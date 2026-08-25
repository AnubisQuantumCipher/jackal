#!/usr/bin/env python3
"""Fail closed on unqualified spacecraft assurance language."""

from __future__ import annotations

import argparse
import html
from html.parser import HTMLParser
import json
import re
import unicodedata
from pathlib import Path
from typing import Sequence


MODEL_QUALIFIER = (
    "under the stated finite-burn ODE model, supplied input bounds, "
    "and machine-checked interval-certificate assumptions"
)
QUALIFIED_VERDICT = f"CERTIFIED SAFE {MODEL_QUALIFIER}"
INSTRUMENT_VALIDATION_PATH = Path(
    "spacecraft_burn_cert/evidence/instrument_validation_v2.json"
)
QUALIFIED_PATTERN = re.compile(
    r"\s+".join(map(re.escape, QUALIFIED_VERDICT.split()))
    + r"(?=(?:[.!?](?:[*_`]+)?|(?:[*_`]+)[.!?])(?:\s|$)|(?:[*_`]+)?\s*$)",
    re.IGNORECASE,
)
TEXT_TARGETS = (
    Path("README.md"),
    Path("spacecraft_burn_cert/README.md"),
    Path("spacecraft_burn_cert/REPORT.md"),
    Path("plugins/jackel/skills/jackel/SKILL.md"),
    Path("release/spacecraft_burn_v175_release_notes.md"),
)
JSON_TARGETS = (
    Path("spacecraft_burn_cert/request_v2.json"),
    Path("spacecraft_burn_cert/evidence/baseline_receipt_v2.json"),
    Path("spacecraft_burn_cert/evidence/baseline_witness_v2.manifest.json"),
    Path("spacecraft_burn_cert/evidence/independent_verification_v2.json"),
    INSTRUMENT_VALIDATION_PATH,
    Path("spacecraft_burn_cert/evidence/mutation_aba_v2.json"),
    Path("release/evidence/spacecraft_burn_proof_identity_v1.json"),
    Path("release/evidence/spacecraft_burn_review_clearance_v1.json"),
    Path("release/evidence/spacecraft_burn_release_readback_v174.json"),
    Path("release/evidence/spacecraft_burn_review_clearance_v175.json"),
    Path("release/evidence/spacecraft_burn_release_metadata_v175.json"),
)
TARGETS = TEXT_TARGETS + JSON_TARGETS
BOUNDED_ASSURANCE_SEPARATOR = r"(?:[\W_]){1,16}"
FORBIDDEN = {
    "proved-safe": re.compile(
        rf"\bPROVED{BOUNDED_ASSURANCE_SEPARATOR}SAFE\b", re.IGNORECASE
    ),
    "proved-unsafe": re.compile(
        rf"\bPROVED{BOUNDED_ASSURANCE_SEPARATOR}UNSAFE\b", re.IGNORECASE
    ),
    "formally-proved-result": re.compile(
        rf"\bformally{BOUNDED_ASSURANCE_SEPARATOR}proved\b", re.IGNORECASE
    ),
}
UNQUALIFIED_CERTIFIED_SAFE_PATTERN = re.compile(
    rf"\bCERTIFIED{BOUNDED_ASSURANCE_SEPARATOR}SAFE\b", re.IGNORECASE
)
ASSURANCE_KEYWORDS = (
    "CERTIFIED",
    "PROVED",
    "SAFE",
    "UNSAFE",
    "FORMAL",
    "FORMALLY",
)
DEFAULT_IGNORABLE_RANGES = (
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)


class AssuranceTextHTMLParser(HTMLParser):
    """Collect visible text while retaining comments for the hidden-text pass."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.boundary_chunks: list[str] = []
        self.accessible_attributes: list[str] = []

    def handle_data(self, data: str) -> None:
        self.chunks.append(data)
        self.boundary_chunks.append(data)

    def handle_comment(self, data: str) -> None:
        self.chunks.append(data)
        self.boundary_chunks.append(data)

    def handle_starttag(
        self, _tag: str, attributes: list[tuple[str, str | None]]
    ) -> None:
        self.boundary_chunks.append(" ")
        self.accessible_attributes.extend(
            value
            for name, value in attributes
            if name.lower() in {"alt", "aria-label", "title"} and value
        )

    def handle_endtag(self, _tag: str) -> None:
        self.boundary_chunks.append(" ")


def html_text(text: str) -> str:
    return html_text_variants(text)[0]


def html_text_variants(text: str) -> tuple[str, ...]:
    parser = AssuranceTextHTMLParser()
    parser.feed(text)
    parser.close()
    return tuple(dict.fromkeys((
        "".join(parser.chunks),
        "".join(parser.boundary_chunks),
        *parser.accessible_attributes,
    )))


def rendered_assurance_text_variants(text: str) -> tuple[str, ...]:
    text = unicodedata.normalize("NFKC", text)
    text = "".join(char for char in text if not disallowed_unicode_control(char))
    rendered = re.sub(r"<!--(.*?)-->", r"\1", text, flags=re.DOTALL)
    rendered = html.unescape(rendered)
    rendered = unicodedata.normalize("NFKC", rendered)
    rendered = "".join(
        char for char in rendered if not disallowed_unicode_control(char)
    )
    rendered = re.sub(r"\\\r?\n", "\n", rendered)
    rendered = re.sub(r"<br\s*/?\s*>", "\n", rendered, flags=re.IGNORECASE)
    variants = []
    for variant in html_text_variants(rendered):
        variant = re.sub(r"!?\[([^\]\n]+)\]\([^\n)]*\)", r"\1", variant)
        variant = re.sub(
            r"!?\[([^\]\n]+)\]\s*\[[^\]\n]*\]", r"\1", variant
        )
        variant = variant.replace("[", "").replace("]", "")
        variant = re.sub(r"\\([\\`*{}\[\]()#+.!_>\- ])", r"\1", variant)
        variants.extend((variant, re.sub(r"[*_`]", "", variant)))
    return tuple(dict.fromkeys(variants))


def rendered_assurance_text(text: str) -> str:
    return rendered_assurance_text_variants(text)[0]


def assurance_text_variants(text: str) -> tuple[str, ...]:
    comments_removed = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    rendered = (
        *rendered_assurance_text_variants(text),
        *rendered_assurance_text_variants(comments_removed),
    )
    without_combining_marks = tuple(
        "".join(
            char
            for char in unicodedata.normalize("NFKD", variant)
            if not unicodedata.category(char).startswith("M")
        )
        for variant in rendered
    )
    return tuple(dict.fromkeys((*rendered, *without_combining_marks)))


def disallowed_unicode_control(char: str) -> bool:
    codepoint = ord(char)
    return char not in "\n\r\t" and (
        unicodedata.category(char) in {"Cc", "Cf"}
        or any(start <= codepoint <= end for start, end in DEFAULT_IGNORABLE_RANGES)
    )


def confusable_assurance_token(text: str) -> bool:
    for variant in assurance_text_variants(text):
        for token in re.findall(r"[^\W\d_]+", variant, flags=re.UNICODE):
            if token.isascii():
                continue
            for keyword in ASSURANCE_KEYWORDS:
                if len(token) == len(keyword) and all(
                    (not char.isascii()) or char.upper() == expected
                    for char, expected in zip(token, keyword)
                ):
                    return True
    return False


def string_findings(value: str, relative: Path, location: str) -> list[dict]:
    variants = assurance_text_variants(value)
    findings = []
    if any(
        disallowed_unicode_control(char)
        for char in (value + html.unescape(value))
    ):
        findings.append({
            "file": str(relative),
            "json_path": location,
            "reason": "unicode-format-or-control",
        })
    if confusable_assurance_token(value):
        findings.append({
            "file": str(relative),
            "json_path": location,
            "reason": "unicode-confusable-assurance-token",
        })
    for reason, pattern in FORBIDDEN.items():
        if any(pattern.search(normalized) for normalized in variants):
            findings.append({"file": str(relative), "json_path": location, "reason": reason})
    if any(
        UNQUALIFIED_CERTIFIED_SAFE_PATTERN.search(
            QUALIFIED_PATTERN.sub("", normalized)
        )
        for normalized in variants
    ):
        findings.append({
            "file": str(relative),
            "json_path": location,
            "reason": "unqualified-certified-safe",
        })
    return findings


def structured_assurance_complete(
    record: dict, required_checker_status: str | None = None
) -> bool:
    classification = record.get("evidence_classification")
    if isinstance(classification, dict):
        classification = classification.get("overall")
    if (
        record.get("verdict_qualifier") != MODEL_QUALIFIER
        or record.get("producer_assurance") != "candidate-only"
        or not isinstance(classification, str)
    ):
        return False
    checker_status = record.get("formal_checker_status")
    if required_checker_status is not None and checker_status != required_checker_status:
        return False
    if checker_status == "ACCEPT":
        return classification == "formal-bounded"
    if checker_status == "NOT_EXECUTED":
        return classification == "rigorously interval-bounded, not formal-bounded"
    return False


def structured_verdict_location_allowed(
    relative: Path, document_schema: object, location: str
) -> bool:
    if relative == Path("spacecraft_burn_cert/evidence/baseline_receipt_v2.json"):
        return (
            document_schema == "spacecraft-finite-burn-formal-receipt-v2"
            and location == "$.verdict"
        )
    if relative == Path("spacecraft_burn_cert/evidence/instrument_validation_v2.json"):
        return (
            document_schema == "spacecraft-finite-burn-instrument-validation-v2"
            and re.fullmatch(r"\$\.step_refinement\.runs\[[0-9]+\]\.verdict", location)
            is not None
        )
    return False


def json_findings(
    value: object,
    relative: Path,
    location: str = "$",
    document_schema: object = None,
) -> list[dict]:
    findings = []
    if isinstance(value, dict):
        verdict = value.get("verdict")
        structured_verdict = isinstance(verdict, str) and re.search(
            r"CERTIFIED\s+SAFE",
            rendered_assurance_text(verdict),
            re.IGNORECASE,
        ) is not None
        if structured_verdict:
            verdict_location = f"{location}.verdict"
            canonical = re.fullmatch(
                r"CERTIFIED\s+SAFE", verdict, re.IGNORECASE
            ) is not None
            if not canonical:
                findings.append({
                    "file": str(relative),
                    "json_path": verdict_location,
                    "reason": "noncanonical-structured-verdict",
                })
            elif not structured_verdict_location_allowed(
                relative, document_schema, verdict_location
            ):
                findings.append({
                    "file": str(relative),
                    "json_path": verdict_location,
                    "reason": "unrecognized-structured-verdict",
                })
            elif not structured_assurance_complete(
                value,
                required_checker_status=(
                    "ACCEPT"
                    if relative
                    == Path("spacecraft_burn_cert/evidence/baseline_receipt_v2.json")
                    else None
                ),
            ):
                findings.append({
                    "file": str(relative),
                    "json_path": verdict_location,
                    "reason": "incomplete-structured-assurance",
                })
        for key, item in value.items():
            child = f"{location}.{key}"
            if structured_verdict and key == "verdict":
                continue
            findings.extend(json_findings(item, relative, child, document_schema))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(
                json_findings(item, relative, f"{location}[{index}]", document_schema)
            )
    elif isinstance(value, str):
        findings.extend(string_findings(value, relative, location))
    return findings


def instrument_assurance_findings(value: object, relative: Path) -> list[dict]:
    if relative != INSTRUMENT_VALIDATION_PATH:
        return []
    if (
        not isinstance(value, dict)
        or value.get("schema") != "spacecraft-finite-burn-instrument-validation-v2"
    ):
        return [{
            "file": str(relative),
            "json_path": "$.schema",
            "reason": "invalid-instrument-schema",
        }]
    refinement = value.get("step_refinement")
    records = refinement.get("runs") if isinstance(refinement, dict) else None
    expected = (
        (
            "1/16",
            "NOT_EXECUTED",
            "rigorously interval-bounded, not formal-bounded",
        ),
        ("1/32", "ACCEPT", "formal-bounded"),
        (
            "1/48",
            "NOT_EXECUTED",
            "rigorously interval-bounded, not formal-bounded",
        ),
    )
    valid = isinstance(records, list) and len(records) == len(expected)
    if valid:
        for record, (step, checker_status, classification) in zip(records, expected):
            if not isinstance(record, dict) or (
                record.get("step_exact"),
                record.get("verdict"),
                record.get("verdict_qualifier"),
                record.get("producer_assurance"),
                record.get("formal_checker_status"),
                record.get("evidence_classification"),
            ) != (
                step,
                "CERTIFIED SAFE",
                MODEL_QUALIFIER,
                "candidate-only",
                checker_status,
                classification,
            ):
                valid = False
                break
    if valid:
        return []
    return [{
        "file": str(relative),
        "json_path": "$.step_refinement.runs",
        "reason": "invalid-refinement-assurance-layout",
    }]


def document_findings(value: object, relative: Path) -> list[dict]:
    schema = value.get("schema") if isinstance(value, dict) else None
    return json_findings(value, relative, document_schema=schema) + instrument_assurance_findings(
        value, relative
    )


class DuplicateJsonKey(ValueError):
    pass


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey(key)
        result[key] = value
    return result


def scan_instrument_validation(path: Path) -> dict:
    relative = INSTRUMENT_VALIDATION_PATH
    findings = []
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys
        )
    except DuplicateJsonKey:
        findings.append({"file": str(relative), "reason": "duplicate-json-key"})
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        findings.append({"file": str(relative), "reason": "invalid-json"})
    else:
        findings.extend(document_findings(payload, relative))
    return {
        "status": "PASS" if not findings else "FAIL",
        "surface_count": 1,
        "forbidden_current_surface_count": len(findings),
        "findings": findings,
    }


def scan(root: Path) -> dict:
    findings = []
    for relative in TEXT_TARGETS:
        path = root / relative
        if not path.is_file():
            findings.append({"file": str(relative), "reason": "missing-publication-surface"})
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            findings.append({"file": str(relative), "reason": "invalid-text-surface"})
            continue
        findings.extend(string_findings(text, relative, "$"))
    for relative in JSON_TARGETS:
        path = root / relative
        if not path.is_file():
            findings.append({"file": str(relative), "reason": "missing-publication-surface"})
            continue
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys
            )
        except DuplicateJsonKey:
            findings.append({"file": str(relative), "reason": "duplicate-json-key"})
            continue
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            findings.append({"file": str(relative), "reason": "invalid-json"})
            continue
        findings.extend(document_findings(payload, relative))
    return {
        "status": "PASS" if not findings else "FAIL",
        "surface_count": len(TEXT_TARGETS) + len(JSON_TARGETS),
        "forbidden_current_surface_count": len(findings),
        "findings": findings,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--instrument-validation", type=Path)
    args = parser.parse_args(argv)
    result = (
        scan_instrument_validation(args.instrument_validation.resolve())
        if args.instrument_validation
        else scan(args.root.resolve())
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
