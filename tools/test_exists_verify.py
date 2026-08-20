#!/usr/bin/env python3
"""Independent checker for `jackal-test-exists-cert-v1`.

The engine validates only the canonical FORM of caller-supplied structural
facts. This checker recomputes every claimed field from the real bytes on disk
and rejects any mismatch, which is what makes the certificate sound: a caller
who misstates a content hash, a line number, or a declaration count cannot mint
an accepted claim.

Verdicts are printed on the final line as `ACCEPT` or `REFUSE <reason-class>`,
and the exit status is 0 only for ACCEPT.

Scope, stated as a permanent nonclaim
-------------------------------------
This checker establishes that a *declaration-shaped occurrence* of a named
symbol exists in a file whose content hash is exactly as claimed. It does NOT
establish that:

  * the test executes, or passes, or is collected by any runner;
  * the test asserts anything at all;
  * the test covers the behaviour a surrounding document claims it covers.

That last gap is deliberate and is the reason `claim-cites-test` exists as a
separate operation: resolving a citation is not the same as validating it. A
document may cite a real test that checks something entirely different. This
checker cannot see that, and says so rather than implying otherwise.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA = "jackal-test-exists-cert-v1"
KINDS = ("test-exists", "claim-cites-test")
MAX_FILE_BYTES = 4 * 1024 * 1024
ENVELOPE_PREFIX = "test-exists-cert="

# Declaration shapes, per language. Each pattern must anchor the symbol with a
# word boundary so `foo` never matches `foo_bar`.
_DECLARATION_PATTERNS = (
    r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+{sym}\s*[(<]",          # Rust
    r"^\s*(?:async\s+)?def\s+{sym}\s*\(",                       # Python
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+{sym}\s*\(",    # JS/TS
    r"^\s*func\s+(?:\([^)]*\)\s*)?{sym}\s*\(",                  # Go
    r"^\s*(?:public|private|protected)?\s*(?:static\s+)?[\w<>\[\],\s]*\b{sym}\s*\([^;]*\)\s*\{{",  # Java/C#
    r"^\s*(?:it|test|describe)\s*\(\s*['\"]{sym}['\"]",         # JS test names
)


class Refusal(Exception):
    def __init__(self, reason_class: str, detail: str = "") -> None:
        super().__init__(f"{reason_class}{': ' + detail if detail else ''}")
        self.reason_class = reason_class
        self.detail = detail


def _safe_relative(root: Path, raw: str, field: str) -> Path:
    if raw.startswith("/") or "\\" in raw:
        raise Refusal("cert-path-unsafe", f"{field} is not repository-relative")
    if any(part == ".." for part in Path(raw).parts):
        raise Refusal("cert-path-unsafe", f"{field} contains a parent traversal")

    # The symlink check MUST precede resolution. `Path.resolve()` follows every
    # link, so `resolved.is_symlink()` is dead code that can never fire — an
    # earlier revision of this function had exactly that bug and a review caught
    # it. Test each component of the unresolved path with `lstat`, which does not
    # follow links, so a link anywhere on the path is refused.
    joined = root / raw
    probe = root
    for part in Path(raw).parts:
        probe = probe / part
        if probe.is_symlink():
            raise Refusal(
                "cert-path-symlink",
                f"{field} traverses or names a symlink at {probe.relative_to(root)}",
            )

    resolved = joined.resolve()
    root_resolved = root.resolve()
    if root_resolved != resolved and root_resolved not in resolved.parents:
        raise Refusal("cert-path-escape", f"{field} escapes the repository root")
    if not resolved.is_file():
        raise Refusal("cert-file-missing", f"{field} does not name a regular file")
    return resolved


def _read_checked(path: Path, field: str) -> bytes:
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise Refusal("cert-file-oversize", f"{field} exceeds {MAX_FILE_BYTES} bytes")
    return raw


def _require_hex64(value: object, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise Refusal("cert-field-shape", f"{field} is not 64 lowercase hex digits")
    return value


def _require_symbol(value: object, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,256}", value):
        raise Refusal("cert-field-shape", f"{field} is not a [A-Za-z0-9_] identifier")
    return value


def _require_canonical_uint(value: object, field: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]{0,17}", value):
        raise Refusal("cert-field-shape", f"{field} is not a canonical decimal integer")
    return int(value)


def _blank_noncode(text: str) -> str:
    """Replace comment and string-literal content with spaces, preserving lines.

    Without this, a symbol named inside a docstring, a Rust `r"..."` literal, or a
    Java multi-line string matches the declaration patterns and a `test-exists`
    certificate can be minted at `assurance_ceiling: exact` for a symbol that is
    never declared. A review found exactly that hole. Newlines are preserved so
    reported line numbers stay correct.

    This is a lexer approximation, not a parser. It is deliberately conservative:
    it may blank slightly too much (losing a real declaration and refusing), never
    too little (admitting a fake one). For Python the `ast` path below supersedes
    it entirely.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    quote: str | None = None
    in_line_comment = False
    in_block_comment = False
    while i < n:
        ch = text[i]
        two = text[i : i + 2]
        three = text[i : i + 3]
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                out.append(ch)
            else:
                out.append(" ")
            i += 1
            continue
        if in_block_comment:
            if two == "*/":
                in_block_comment = False
                out.append("  ")
                i += 2
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue
        if quote is not None:
            if ch == "\\":
                out.append("  ")
                i += 2
                continue
            if text.startswith(quote, i):
                out.append(" " * len(quote))
                i += len(quote)
                quote = None
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue
        if two == "//" or ch == "#":
            in_line_comment = True
            continue
        if two == "/*":
            in_block_comment = True
            i += 2
            out.append("  ")
            continue
        if three in ('"""', "'''"):
            quote = three
            out.append("   ")
            i += 3
            continue
        if ch in ('"', "'"):
            quote = ch
            out.append(" ")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _python_declarations(text: str, symbol: str) -> list[int] | None:
    """Exact declaration lines via `ast`, or None if the source will not parse."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == symbol:
                lines.add(node.lineno)
    return sorted(lines)


def find_declarations(text: str, symbol: str, *, suffix: str = "") -> list[int]:
    """1-based line numbers of declaration-shaped occurrences of `symbol`.

    For Python sources the answer comes from `ast` and is exact. For every other
    language it comes from declaration patterns applied to source with comments
    and string literals blanked out.
    """
    if suffix == ".py":
        exact = _python_declarations(text, symbol)
        if exact is not None:
            return exact

    scannable = _blank_noncode(text)
    escaped = re.escape(symbol)
    compiled = [
        re.compile(pattern.format(sym=escaped), re.MULTILINE)
        for pattern in _DECLARATION_PATTERNS
    ]
    hits: set[int] = set()
    for index, line in enumerate(scannable.splitlines(), start=1):
        for pattern in compiled:
            if pattern.match(line):
                hits.add(index)
                break
    return sorted(hits)


def _verify_test_exists(root: Path, claim: dict) -> list[str]:
    expected_keys = {
        "declaration_count",
        "declaration_line",
        "file_path",
        "file_sha256",
        "symbol",
    }
    if set(claim) != expected_keys:
        raise Refusal("cert-claim-keys", f"expected exactly {sorted(expected_keys)}")

    file_path = claim["file_path"]
    if not isinstance(file_path, str):
        raise Refusal("cert-field-shape", "file_path is not a string")
    claimed_sha = _require_hex64(claim["file_sha256"], "file_sha256")
    symbol = _require_symbol(claim["symbol"], "symbol")
    claimed_line = _require_canonical_uint(claim["declaration_line"], "declaration_line")
    claimed_count = _require_canonical_uint(claim["declaration_count"], "declaration_count")
    if claimed_line == 0:
        raise Refusal("cert-field-shape", "declaration_line is 1-based and must not be 0")
    if claimed_count == 0:
        raise Refusal("cert-absence-as-existence", "declaration_count 0 is an absence")

    resolved = _safe_relative(root, file_path, "file_path")
    raw = _read_checked(resolved, "file_path")

    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != claimed_sha:
        raise Refusal(
            "cert-content-hash-mismatch",
            f"file_sha256 claimed {claimed_sha} but bytes hash to {actual_sha}",
        )

    text = raw.decode("utf-8", errors="replace")
    lines = find_declarations(text, symbol, suffix=resolved.suffix)
    if not lines:
        raise Refusal(
            "cert-symbol-absent",
            f"no declaration-shaped occurrence of {symbol!r} in {file_path}",
        )
    if len(lines) != claimed_count:
        raise Refusal(
            "cert-declaration-count-mismatch",
            f"declaration_count claimed {claimed_count} but found {len(lines)} at lines {lines}",
        )
    if claimed_line not in lines:
        raise Refusal(
            "cert-declaration-line-mismatch",
            f"declaration_line claimed {claimed_line} but declarations are at {lines}",
        )
    return [
        f"file_sha256 recomputed {actual_sha}",
        f"symbol {symbol} declared at {lines}",
        f"declaration_count {len(lines)}",
    ]


def _verify_claim_cites_test(root: Path, claim: dict) -> list[str]:
    expected_keys = {
        "claim_text",
        "doc_path",
        "doc_sha256",
        "symbol",
        "test_path",
        "test_sha256",
    }
    if set(claim) != expected_keys:
        raise Refusal("cert-claim-keys", f"expected exactly {sorted(expected_keys)}")

    claim_text = claim["claim_text"]
    if not isinstance(claim_text, str) or not claim_text:
        raise Refusal("cert-field-shape", "claim_text is not a non-empty string")
    doc_sha = _require_hex64(claim["doc_sha256"], "doc_sha256")
    test_sha = _require_hex64(claim["test_sha256"], "test_sha256")
    symbol = _require_symbol(claim["symbol"], "symbol")

    doc = _safe_relative(root, claim["doc_path"], "doc_path")
    doc_raw = _read_checked(doc, "doc_path")
    actual_doc_sha = hashlib.sha256(doc_raw).hexdigest()
    if actual_doc_sha != doc_sha:
        raise Refusal(
            "cert-content-hash-mismatch",
            f"doc_sha256 claimed {doc_sha} but bytes hash to {actual_doc_sha}",
        )
    doc_text = doc_raw.decode("utf-8", errors="replace")
    if claim_text not in doc_text:
        raise Refusal(
            "cert-claim-text-absent",
            "claim_text does not occur verbatim in doc_path",
        )

    test = _safe_relative(root, claim["test_path"], "test_path")
    test_raw = _read_checked(test, "test_path")
    actual_test_sha = hashlib.sha256(test_raw).hexdigest()
    if actual_test_sha != test_sha:
        raise Refusal(
            "cert-content-hash-mismatch",
            f"test_sha256 claimed {test_sha} but bytes hash to {actual_test_sha}",
        )
    test_text = test_raw.decode("utf-8", errors="replace")
    lines = find_declarations(test_text, symbol, suffix=test.suffix)
    if not lines:
        raise Refusal(
            "cert-citation-dangling",
            f"claim cites {symbol!r} but no such declaration exists in {claim['test_path']}",
        )
    return [
        f"doc_sha256 recomputed {actual_doc_sha}",
        "claim_text found verbatim in doc_path",
        f"cited symbol {symbol} declared at {lines}",
        "NOTE: citation resolves; whether the cited test covers the claim is NOT established",
    ]


def parse_envelope(raw: str) -> dict:
    text = raw.strip()
    if text.startswith(ENVELOPE_PREFIX):
        text = text[len(ENVELOPE_PREFIX) :]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Refusal("cert-not-json", str(exc)) from exc
    if not isinstance(payload, dict):
        raise Refusal("cert-not-object", "certificate is not a JSON object")
    if set(payload) != {"claim", "kind", "schema", "witness"}:
        raise Refusal("cert-envelope-keys", "expected exactly claim/kind/schema/witness")
    if payload["schema"] != SCHEMA:
        raise Refusal("cert-schema-unexpected", f"schema {payload['schema']!r} != {SCHEMA}")
    if payload["kind"] not in KINDS:
        raise Refusal("cert-kind-unexpected", f"kind {payload['kind']!r} not in {KINDS}")
    if not isinstance(payload["claim"], dict):
        raise Refusal("cert-claim-shape", "claim is not an object")
    if payload["witness"] != {}:
        raise Refusal("cert-witness-unexpected", "v1 defines no witness fields")
    return payload


def verify(raw: str, root: Path) -> list[str]:
    payload = parse_envelope(raw)
    if payload["kind"] == "test-exists":
        return _verify_test_exists(root, payload["claim"])
    return _verify_claim_cites_test(root, payload["claim"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cert", help="path to a file holding the certificate line")
    parser.add_argument("--root", default=".", help="repository root for relative paths")
    parser.add_argument("--stdin", action="store_true", help="read the certificate from stdin")
    args = parser.parse_args(argv)

    if bool(args.cert) == bool(args.stdin):
        print("REFUSE cert-input-ambiguous: pass exactly one of --cert or --stdin")
        return 2
    raw = sys.stdin.read() if args.stdin else Path(args.cert).read_text(encoding="utf-8")
    # Tolerate a full command transcript: take the envelope line if present.
    for line in raw.splitlines():
        if line.strip().startswith(ENVELOPE_PREFIX):
            raw = line
            break

    try:
        notes = verify(raw, Path(args.root))
    except Refusal as refusal:
        print(f"REFUSE {refusal.reason_class}: {refusal.detail}".rstrip(": "))
        return 2
    for note in notes:
        print(f"  {note}")
    print("ACCEPT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
