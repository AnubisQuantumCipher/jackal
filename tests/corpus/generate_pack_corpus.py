#!/usr/bin/env python3
"""Frozen domain-pack corpora: engine harness, generator, and self-check.

This module is both the generator that freezes the corpora and the harness the
W6 pack suites drive. Sharing one driver between the freeze and the replay is
deliberate: if the two used different subprocess plumbing, a replay could agree
with a frozen expectation for the wrong reason.

Three case classes, one per column the corpora must cover:

  ``positive``  the engine emits a certificate and the independent checker
                ACCEPTs it.
  ``refusal``   the engine refuses at the form level and emits no certificate.
                The refusal class is read out of the process ``ANUBIS_PANIC``
                line, never asserted from a guess.
  ``poison``    the engine emits a *well-formed* certificate -- because the
                engine validates only canonical form -- and the independent
                checker refuses it on substance. This is the interesting column:
                it is where a caller who misstates a content hash, a line
                number, a declaration count, or a decision margin is stopped.

Nothing in this file is an expected value written by hand. Declaration line
numbers come from ``tools/test_exists_verify.py:find_declarations``; every
recorded stdout, return code, refusal class, and verdict is the observed output
of a real run of the pinned engine and the real checkers.

Usage
-----
  python3 tests/corpus/generate_pack_corpus.py --self-check
  python3 tests/corpus/generate_pack_corpus.py --freeze

``--self-check`` re-derives every argument from the fixtures on disk, re-runs
the engine and the checkers, recomputes the aggregate digest, and refuses on any
divergence. ``--freeze`` rewrites the corpus files from observed output.

Nonclaims
---------
A frozen corpus records what the engine and the checkers *did*. It does not
establish that the recorded behaviour is correct, that the refusal classes are
exhaustive, or that a certificate the checker ACCEPTs says anything about the
code the certificate names. It is a regression witness, not a proof.
"""

from __future__ import annotations

import argparse
import atexit
import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
CORPUS_SCHEMA = "jackal-pack-corpus-v1"
DIGEST_KEY = "corpus_digest_sha256"

ANUBIS = Path(
    os.environ.get(
        "ANUBIS_BIN",
        "/Users/sicarii/anubis-lang/vm/pins/anubis-a733565f237d",
    )
)
FIXED_PATH = "/Users/sicarii/.cargo/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CHECKER_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

TEST_EXISTS_CHECKER = "tools/test_exists_verify.py"
DECISION_CHECKER = "tools/decision_verify.py"
TEST_EXISTS_PREFIX = "test-exists-cert="
DECISION_PREFIX = "decision-cert="

PROGRAMMING_PACK = "jackal.programming.source"
DECISION_PACK = "jackal.decision.matrix"
OP_TEST_EXISTS = "programming.source.test_exists.v1"
OP_CLAIM_CITES = "programming.source.claim_cites_test.v1"
OP_DECISION_RANK = "decision.matrix.rank.v1"
OP_DECISION_RANK_V2 = "decision.matrix.rank.v2"
UNIT_REGISTRY = "release/claim/unit_registry_v1.json"
# The one canonical unit id the v2 lane deliberately does NOT admit. Declaring
# the dimensionless identity says nothing about what the numbers measure, so it
# would reopen the escape hatch the closed vocabulary exists to shut.
UNIT_REGISTRY_EXCLUSIONS = ("one",)

# `ANUBIS_PANIC: <class>: <detail>`. The trailing colon is required so the
# engine's generic `wrong number of arguments` panic -- which names no class --
# is not misread as a class called "wrong".
_PANIC_RE = re.compile(r"ANUBIS_PANIC: ([a-z0-9][a-z0-9-]*): (.*)")


class CorpusError(RuntimeError):
    """A corpus could not be generated or failed its self-check."""


# --------------------------------------------------------------------------
# checker access
# --------------------------------------------------------------------------


def _load_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    if spec is None or spec.loader is None:
        raise CorpusError(f"cannot load {relative}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_TEST_EXISTS_MODULE = None


def test_exists_module():
    """The real checker, imported so line numbers are never hand-written."""
    global _TEST_EXISTS_MODULE
    if _TEST_EXISTS_MODULE is None:
        _TEST_EXISTS_MODULE = _load_module("jackal_test_exists_verify", TEST_EXISTS_CHECKER)
    return _TEST_EXISTS_MODULE


def sha256_file(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def admitted_units_from_registry() -> tuple[str, ...]:
    """The v2 closed unit vocabulary, derived from the pinned registry file.

    Single derivation used by both the corpus and `tests/decision_pack_test.py`,
    so the engine's hardcoded list and the checker's mirror are always compared
    against the registry rather than against a retyped copy of themselves.
    """
    document = json.loads((ROOT / UNIT_REGISTRY).read_text(encoding="utf-8"))
    if document.get("schema") != "jackal-unit-registry-v1":
        raise CorpusError(f"{UNIT_REGISTRY} is not jackal-unit-registry-v1")
    units = document.get("units")
    if not isinstance(units, dict) or not units:
        raise CorpusError(f"{UNIT_REGISTRY} declares no units")
    missing = [name for name in UNIT_REGISTRY_EXCLUSIONS if name not in units]
    if missing:
        raise CorpusError(
            f"excluded unit ids are absent from {UNIT_REGISTRY}, so the exclusion "
            f"list is stale rather than deliberate: {missing}"
        )
    return tuple(name for name in units if name not in UNIT_REGISTRY_EXCLUSIONS)


def declarations(relative: str, symbol: str) -> list[int]:
    """Declaration lines for `symbol`, as the checker itself computes them."""
    path = ROOT / relative
    text = path.read_bytes().decode("utf-8", errors="replace")
    return test_exists_module().find_declarations(text, symbol, suffix=path.suffix)


def declaration_line(relative: str, symbol: str, index: int = 0) -> str:
    lines = declarations(relative, symbol)
    if not lines:
        raise CorpusError(f"{relative} declares no {symbol!r}; fixture drifted")
    return str(lines[index])


def declaration_count(relative: str, symbol: str) -> str:
    lines = declarations(relative, symbol)
    if not lines:
        raise CorpusError(f"{relative} declares no {symbol!r}; fixture drifted")
    return str(len(lines))


# --------------------------------------------------------------------------
# engine harness
# --------------------------------------------------------------------------


class Observation:
    __slots__ = ("returncode", "stdout", "stderr", "refusal_class", "refusal_detail")

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        match = _PANIC_RE.search(stderr)
        self.refusal_class = match.group(1) if match else None
        self.refusal_detail = match.group(2).strip() if match else None

    def certificate(self, prefix: str) -> str:
        lines = [line for line in self.stdout.splitlines() if line.startswith(prefix)]
        if len(lines) != 1:
            raise CorpusError(f"expected exactly one {prefix} line, found {len(lines)}")
        return lines[0]


class Engine:
    """Drives the pinned JACKAL engine, building it at most once per process.

    ``./jackal`` shells out to ``anubis run``, which recompiles the engine on
    every invocation (~9.3 s observed). A corpus with dozens of cases cannot pay
    that per case, so this harness builds once through ``./jackal`` and then
    execs the native binary the pinned compiler left in its ``--out`` directory.

    That shortcut is only sound if the two paths are the same engine, so
    ``__init__`` proves it rather than assuming it: the launcher's stdout for a
    canonical probe must be byte-identical to the fast path's stdout for the
    same probe. If the compiler layout ever changes and no binary appears, the
    harness falls back to the launcher for every call and says so in ``mode``.
    """

    _shared: "Engine | None" = None

    PROBE = ("mod-pow", "2", "10", "1000")

    def __init__(self) -> None:
        if not ANUBIS.is_file():
            raise CorpusError(f"pinned Anubis compiler unavailable at {ANUBIS}")
        self.out = Path(tempfile.mkdtemp(prefix="jackal-pack-corpus-out-"))
        atexit.register(shutil.rmtree, self.out, True)
        self.engine_source_sha256 = sha256_file("jackal_calc.anb")
        self.anubis_pin = ANUBIS.name
        launcher = self._run_via_launcher(self.PROBE)
        if launcher.returncode != 0:
            raise CorpusError(f"engine build probe failed: {launcher.stderr[-2000:]}")
        native = self.out / "anubis_run"
        if native.is_file() and os.access(native, os.X_OK):
            self.native = native
            self.mode = "prebuilt-native"
            direct = self._run_via_native(self.PROBE)
            if direct.stdout != launcher.stdout or direct.returncode != 0:
                raise CorpusError(
                    "fast path diverges from the launcher for the build probe; "
                    "refusing to use it"
                )
        else:
            self.native = None
            self.mode = "launcher-per-call"
        self.probe_stdout = launcher.stdout

    @classmethod
    def shared(cls) -> "Engine":
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def _environment(self) -> dict[str, str]:
        return {
            "ANUBIS_BIN": os.fspath(ANUBIS),
            "JACKAL_FORCE_SOURCE": "1",
            "JACKAL_OUT": os.fspath(self.out),
            "PATH": FIXED_PATH,
        }

    def _run_via_launcher(self, argv: Iterable[str]) -> Observation:
        completed = subprocess.run(
            [os.fspath(ROOT / "jackal"), *argv],
            cwd=ROOT,
            env=self._environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
            check=False,
        )
        return Observation(
            completed.returncode,
            completed.stdout.decode("utf-8", errors="replace"),
            completed.stderr.decode("utf-8", errors="replace"),
        )

    def _run_via_native(self, argv: Iterable[str]) -> Observation:
        assert self.native is not None
        completed = subprocess.run(
            [os.fspath(self.native), *argv],
            cwd=ROOT,
            env={"PATH": FIXED_PATH},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
            check=False,
        )
        return Observation(
            completed.returncode,
            completed.stdout.decode("utf-8", errors="replace"),
            completed.stderr.decode("utf-8", errors="replace"),
        )

    def run(self, *argv: str) -> Observation:
        if self.native is not None:
            return self._run_via_native(argv)
        return self._run_via_launcher(argv)

    def run_via_launcher(self, *argv: str) -> Observation:
        """Force the full `./jackal` -> `anubis run` path. Slow; used sparingly."""
        return self._run_via_launcher(argv)

    def route(self, pack_id: str, operation_id: str, *argv: str) -> Observation:
        return self.run("pack-route", pack_id, operation_id, *argv)


# --------------------------------------------------------------------------
# independent checkers
# --------------------------------------------------------------------------


class Verdict:
    __slots__ = ("returncode", "stdout", "line", "reason_class")

    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        lines = [line for line in stdout.splitlines() if line.strip()]
        self.line = lines[-1].strip() if lines else ""
        if self.line.startswith("REFUSE "):
            token = self.line[len("REFUSE ") :].split(":", 1)[0].strip()
            self.reason_class = token
        elif self.line == "ACCEPT":
            self.reason_class = None
        else:
            self.reason_class = "cert-verdict-unparseable"

    @property
    def summary(self) -> str:
        return "ACCEPT" if self.reason_class is None else f"REFUSE {self.reason_class}"


def _run_checker(relative: str, argv: list[str], payload: str) -> Verdict:
    completed = subprocess.run(
        ["/usr/bin/python3", "-I", "-S", "-B", os.fspath(ROOT / relative), *argv],
        cwd=ROOT,
        env={"PATH": CHECKER_PATH},
        input=payload.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    if completed.returncode not in (0, 2):
        raise CorpusError(
            f"{relative} exited {completed.returncode}: {completed.stderr.decode()[-800:]}"
        )
    return Verdict(completed.returncode, completed.stdout.decode("utf-8", errors="replace"))


def check_test_exists(certificate: str, root: Path | None = None) -> Verdict:
    target = ROOT if root is None else root
    return _run_checker(
        TEST_EXISTS_CHECKER, ["--stdin", "--root", os.fspath(target)], certificate
    )


def check_decision(certificate: str) -> Verdict:
    return _run_checker(DECISION_CHECKER, ["--stdin"], certificate)


# --------------------------------------------------------------------------
# certificate tampering, declaratively recorded
# --------------------------------------------------------------------------


def apply_tamper(certificate: str, prefix: str, tamper: dict) -> str:
    """Apply one recorded mutation to a minted certificate.

    Tampering is expressed as data so the corpus row states exactly what was
    changed. A poison case whose mutation lived only in Python would be
    unauditable from the frozen file.
    """
    payload = json.loads(certificate[len(prefix) :])
    operation = tamper["op"]
    if operation == "set_claim":
        cursor: Any = payload["claim"]
        path = tamper["path"]
        for key in path[:-1]:
            cursor = cursor[key]
        cursor[path[-1]] = tamper["value"]
    elif operation == "delete_envelope_key":
        del payload[tamper["key"]]
    elif operation == "delete_claim_key":
        del payload["claim"][tamper["key"]]
    elif operation == "set_envelope_value":
        payload[tamper["key"]] = tamper["value"]
    else:
        raise CorpusError(f"unknown tamper op {operation!r}")
    return prefix + json.dumps(payload, sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------------
# case specifications
# --------------------------------------------------------------------------

PY_FIXTURE = "tests/corpus/fixtures/genuine_python_decls.py"
DOCSTRING_FIXTURE = "tests/corpus/fixtures/poison_docstring_only.py"
RAW_STRING_FIXTURE = "tests/corpus/fixtures/poison_rust_raw_string.rs"
LINE_COMMENT_FIXTURE = "tests/corpus/fixtures/poison_rust_line_comment.rs"
BLOCK_COMMENT_FIXTURE = "tests/corpus/fixtures/poison_rust_block_comment.rs"
CLAIM_DOC = "tests/corpus/fixtures/claim_source_doc.md"

CLAIM_RESOLVES = "The fixture module declares a Python helper named corpus_python_target."
CLAIM_DANGLES = (
    "The fixture module declares a Python helper named corpus_absent_from_fixture."
)
WRONG_SHA = "0" * 64


def _test_exists(relative: str, symbol: str, line: str, count: str) -> list[str]:
    return [relative, sha256_file(relative), symbol, line, count]


def _claim_cites(doc: str, claim_text: str, test: str, symbol: str) -> list[str]:
    return [doc, sha256_file(doc), claim_text, test, sha256_file(test), symbol]


def programming_specs() -> list[dict]:
    """Every programming-pack case, with arguments derived from the fixtures."""
    specs: list[dict] = []

    def add(**row: Any) -> None:
        specs.append(row)

    # ---- positive -------------------------------------------------------
    add(
        case_id="positive_test_exists_single_declaration",
        case_class="positive",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(
            PY_FIXTURE,
            "corpus_python_target",
            declaration_line(PY_FIXTURE, "corpus_python_target"),
            declaration_count(PY_FIXTURE, "corpus_python_target"),
        ),
        note="one genuine Python declaration, line and count derived from find_declarations",
    )
    add(
        case_id="positive_test_exists_two_declarations_first_line",
        case_class="positive",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(
            PY_FIXTURE,
            "corpus_python_twice",
            declaration_line(PY_FIXTURE, "corpus_python_twice", 0),
            declaration_count(PY_FIXTURE, "corpus_python_twice"),
        ),
        note="a name declared twice; declaration_count 2 must be stated truthfully",
    )
    add(
        case_id="positive_test_exists_two_declarations_second_line",
        case_class="positive",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(
            PY_FIXTURE,
            "corpus_python_twice",
            declaration_line(PY_FIXTURE, "corpus_python_twice", 1),
            declaration_count(PY_FIXTURE, "corpus_python_twice"),
        ),
        note="declaration_line must be one of the declarations, not only the first",
    )
    add(
        case_id="positive_test_exists_class_declaration",
        case_class="positive",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(
            PY_FIXTURE,
            "CorpusPythonHolder",
            declaration_line(PY_FIXTURE, "CorpusPythonHolder"),
            declaration_count(PY_FIXTURE, "CorpusPythonHolder"),
        ),
        note="a class declaration is a declaration for this checker",
    )
    add(
        case_id="positive_test_exists_docstring_fixture_anchor",
        case_class="positive",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(
            DOCSTRING_FIXTURE,
            "corpus_docstring_anchor",
            declaration_line(DOCSTRING_FIXTURE, "corpus_docstring_anchor"),
            declaration_count(DOCSTRING_FIXTURE, "corpus_docstring_anchor"),
        ),
        note="control: the file whose phantom is refused still yields its real symbol",
    )
    add(
        case_id="positive_test_exists_rust_raw_string_fixture_anchor",
        case_class="positive",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(
            RAW_STRING_FIXTURE,
            "corpus_rust_raw_anchor",
            declaration_line(RAW_STRING_FIXTURE, "corpus_rust_raw_anchor"),
            declaration_count(RAW_STRING_FIXTURE, "corpus_rust_raw_anchor"),
        ),
        note="control for the non-Python blanking path: a real Rust fn is found",
    )
    add(
        case_id="positive_test_exists_rust_comment_fixture_anchor",
        case_class="positive",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(
            LINE_COMMENT_FIXTURE,
            "corpus_rust_comment_anchor",
            declaration_line(LINE_COMMENT_FIXTURE, "corpus_rust_comment_anchor"),
            declaration_count(LINE_COMMENT_FIXTURE, "corpus_rust_comment_anchor"),
        ),
        note="control: comment blanking does not blind the scanner to real code",
    )
    add(
        case_id="positive_test_exists_rust_block_comment_fixture_anchor",
        case_class="positive",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(
            BLOCK_COMMENT_FIXTURE,
            "corpus_rust_block_anchor",
            declaration_line(BLOCK_COMMENT_FIXTURE, "corpus_rust_block_anchor"),
            declaration_count(BLOCK_COMMENT_FIXTURE, "corpus_rust_block_anchor"),
        ),
        note="control: block-comment blanking does not blind the scanner to real code",
    )
    add(
        case_id="positive_claim_cites_test_citation_resolves",
        case_class="positive",
        operation_id=OP_CLAIM_CITES,
        engine_command="claim-cites-test",
        argv=_claim_cites(CLAIM_DOC, CLAIM_RESOLVES, PY_FIXTURE, "corpus_python_target"),
        note="claim text occurs verbatim in the doc and the cited symbol exists",
    )

    # ---- refusal: engine, form only -------------------------------------
    add(
        case_id="refusal_file_sha256_not_64_hex",
        case_class="refusal",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=[PY_FIXTURE, "deadbeef", "corpus_python_target", "13", "1"],
        expected_refusal="prog-hex64",
    )
    add(
        case_id="refusal_absolute_file_path",
        case_class="refusal",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=["/etc/passwd", WRONG_SHA, "corpus_python_target", "1", "1"],
        expected_refusal="prog-path",
    )
    add(
        case_id="refusal_parent_traversal_file_path",
        case_class="refusal",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=["../etc/passwd", WRONG_SHA, "corpus_python_target", "1", "1"],
        expected_refusal="prog-path",
    )
    add(
        case_id="refusal_symbol_not_an_identifier",
        case_class="refusal",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(PY_FIXTURE, "corpus-python-target", "13", "1"),
        expected_refusal="prog-symbol",
    )
    add(
        case_id="refusal_declaration_line_zero",
        case_class="refusal",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(PY_FIXTURE, "corpus_python_target", "0", "1"),
        expected_refusal="prog-uint",
    )
    add(
        case_id="refusal_declaration_count_zero_is_an_absence",
        case_class="refusal",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(PY_FIXTURE, "corpus_python_target", "13", "0"),
        expected_refusal="prog-absent",
    )
    add(
        case_id="refusal_route_arity_test_exists",
        case_class="refusal",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(PY_FIXTURE, "corpus_python_target", "13", "1")[:4],
        route_only=True,
        expected_refusal="pack-request-arity",
    )
    add(
        case_id="refusal_unknown_pack_id",
        case_class="refusal",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(
            PY_FIXTURE,
            "corpus_python_target",
            declaration_line(PY_FIXTURE, "corpus_python_target"),
            declaration_count(PY_FIXTURE, "corpus_python_target"),
        ),
        route_only=True,
        route_pack_id="jackal.programming.absent",
        expected_refusal="pack-id-unknown",
    )
    add(
        case_id="refusal_unknown_operation_id",
        case_class="refusal",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(
            PY_FIXTURE,
            "corpus_python_target",
            declaration_line(PY_FIXTURE, "corpus_python_target"),
            declaration_count(PY_FIXTURE, "corpus_python_target"),
        ),
        route_only=True,
        route_operation_id="programming.source.absent.v1",
        expected_refusal="pack-operation-unknown",
    )
    add(
        case_id="refusal_empty_claim_text",
        case_class="refusal",
        operation_id=OP_CLAIM_CITES,
        engine_command="claim-cites-test",
        argv=_claim_cites(CLAIM_DOC, "", PY_FIXTURE, "corpus_python_target"),
        expected_refusal="prog-text",
    )
    add(
        case_id="refusal_claim_text_over_2048_bytes",
        case_class="refusal",
        operation_id=OP_CLAIM_CITES,
        engine_command="claim-cites-test",
        argv=_claim_cites(CLAIM_DOC, "x" * 2049, PY_FIXTURE, "corpus_python_target"),
        expected_refusal="prog-text",
    )

    # ---- poison: engine mints, checker refuses ---------------------------
    add(
        case_id="poison_stale_content_hash",
        case_class="poison",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=[
            PY_FIXTURE,
            WRONG_SHA,
            "corpus_python_target",
            declaration_line(PY_FIXTURE, "corpus_python_target"),
            declaration_count(PY_FIXTURE, "corpus_python_target"),
        ],
        expected_verdict="REFUSE cert-content-hash-mismatch",
        note="a well-formed hash that is not the file's hash",
    )
    add(
        case_id="poison_declaration_line_wrong",
        case_class="poison",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(
            PY_FIXTURE,
            "corpus_python_target",
            "999",
            declaration_count(PY_FIXTURE, "corpus_python_target"),
        ),
        expected_verdict="REFUSE cert-declaration-line-mismatch",
    )
    add(
        case_id="poison_declaration_count_inflated",
        case_class="poison",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(
            PY_FIXTURE,
            "corpus_python_target",
            declaration_line(PY_FIXTURE, "corpus_python_target"),
            "2",
        ),
        expected_verdict="REFUSE cert-declaration-count-mismatch",
        note="claiming two declarations of a symbol declared once",
    )
    add(
        case_id="poison_symbol_absent_entirely",
        case_class="poison",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(PY_FIXTURE, "corpus_absent_from_fixture", "1", "1"),
        expected_verdict="REFUSE cert-symbol-absent",
    )
    add(
        case_id="poison_declaration_only_in_python_docstring",
        case_class="poison",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(DOCSTRING_FIXTURE, "corpus_docstring_phantom", "6", "1"),
        expected_verdict="REFUSE cert-symbol-absent",
        note="the symbol is declaration-shaped inside a docstring and nowhere else",
    )
    add(
        case_id="poison_declaration_only_in_rust_raw_string",
        case_class="poison",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(RAW_STRING_FIXTURE, "corpus_raw_string_phantom", "16", "1"),
        expected_verdict="REFUSE cert-symbol-absent",
        note="declaration-shaped text inside an r\"...\" literal is not a declaration",
    )
    add(
        case_id="poison_declaration_only_in_line_comment",
        case_class="poison",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(LINE_COMMENT_FIXTURE, "corpus_line_comment_phantom", "9", "1"),
        expected_verdict="REFUSE cert-symbol-absent",
        note=(
            "commented-out code is not code. Attributed honestly: this one is "
            "refused by the line anchor in the declaration patterns, not by the "
            "comment-blanking pass -- see the instrument test in "
            "tests/programming_pack_test.py"
        ),
    )
    add(
        case_id="poison_declaration_only_in_block_comment",
        case_class="poison",
        operation_id=OP_TEST_EXISTS,
        engine_command="test-exists",
        argv=_test_exists(BLOCK_COMMENT_FIXTURE, "corpus_block_comment_phantom", "15", "1"),
        expected_verdict="REFUSE cert-symbol-absent",
        note=(
            "the phantom line carries no comment marker of its own, so the "
            "comment-blanking pass is the only thing that refuses it"
        ),
    )
    add(
        case_id="poison_claim_text_not_in_document",
        case_class="poison",
        operation_id=OP_CLAIM_CITES,
        engine_command="claim-cites-test",
        argv=_claim_cites(
            CLAIM_DOC,
            "The fixture module proves corpus_python_target is correct.",
            PY_FIXTURE,
            "corpus_python_target",
        ),
        expected_verdict="REFUSE cert-claim-text-absent",
        note="the quoted claim does not occur verbatim in the cited document",
    )
    add(
        case_id="poison_citation_dangles",
        case_class="poison",
        operation_id=OP_CLAIM_CITES,
        engine_command="claim-cites-test",
        argv=_claim_cites(
            CLAIM_DOC, CLAIM_DANGLES, PY_FIXTURE, "corpus_absent_from_fixture"
        ),
        expected_verdict="REFUSE cert-citation-dangling",
        note="the document's sentence is real; the test it names is not",
    )
    return specs


def decision_specs() -> list[dict]:
    specs: list[dict] = []

    def add(**row: Any) -> None:
        specs.append(row)

    add(
        case_id="positive_decision_max",
        case_class="positive",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d_max", "throughput_rps", "max", "alpha", "120", "beta", "400", "gamma", "250"],
        note="argmax over three declared integer values",
    )
    add(
        case_id="positive_decision_min",
        case_class="positive",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d_min", "latency_ms", "min", "alpha", "120", "beta", "90"],
        note="argmin: the sense is part of the claim, not an afterthought",
    )
    add(
        case_id="positive_decision_six_options_upper_bound",
        case_class="positive",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=[
            "d_six", "bytes_written", "max",
            "a", "1", "b", "2", "c", "3", "d", "4", "e", "5", "f", "6",
        ],
        note="the protocol upper bound of six options is admissible",
    )
    add(
        case_id="positive_decision_negative_values",
        case_class="positive",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d_neg", "drift_ppm", "max", "alpha", "-40", "beta", "-7"],
        note="negative integers rank without special-casing",
    )
    add(
        case_id="positive_decision_negative_zero_is_normalised",
        case_class="positive",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d_negzero", "queue_depth", "max", "alpha", "-0", "beta", "2"],
        note=(
            "the engine emits 0 for -0, so the checker's negative-zero refusal "
            "cannot be reached through the engine"
        ),
    )

    add(
        case_id="refusal_criterion_is_a_value_judgment",
        case_class="refusal",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d1", "best_score", "max", "alpha", "1", "beta", "2"],
        expected_refusal="decision-value-judgment",
    )
    add(
        case_id="refusal_top_two_tie",
        case_class="refusal",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d1", "latency_ms", "max", "alpha", "5", "beta", "5"],
        expected_refusal="decision-margin-zero",
    )
    add(
        case_id="refusal_duplicate_label",
        case_class="refusal",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d1", "latency_ms", "max", "alpha", "5", "alpha", "6"],
        expected_refusal="decision-duplicate-label",
    )
    add(
        case_id="refusal_sense_unknown",
        case_class="refusal",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d1", "latency_ms", "maximise", "alpha", "5", "beta", "6"],
        expected_refusal="decision-sense-unknown",
    )
    add(
        case_id="refusal_odd_label_value_pairing",
        case_class="refusal",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d1", "latency_ms", "max", "alpha", "5", "beta"],
        expected_refusal="pack-request-arity",
    )
    add(
        case_id="refusal_fewer_than_two_options",
        case_class="refusal",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d1", "latency_ms", "max", "alpha", "5"],
        expected_refusal="pack-request-arity",
    )
    add(
        case_id="refusal_more_than_six_options",
        case_class="refusal",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=[
            "d1", "latency_ms", "max",
            "a", "1", "b", "2", "c", "3", "d", "4", "e", "5", "f", "6", "g", "7",
        ],
        expected_refusal="pack-request-arity",
    )
    add(
        case_id="refusal_route_unknown_operation_id",
        case_class="refusal",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d1", "latency_ms", "min", "alpha", "120", "beta", "90"],
        route_only=True,
        route_operation_id="decision.matrix.absent.v1",
        expected_refusal="pack-operation-unknown",
    )

    add(
        case_id="poison_selected_relabelled",
        case_class="poison",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        # Three options on purpose. With two, relabelling `selected` to the only
        # other option makes it equal `runner_up`, and the checker refuses on
        # that earlier and narrower ground -- a refusal for the wrong reason,
        # which the corpus generator caught when this case had two options.
        argv=["d_tamper", "latency_ms", "min", "alpha", "120", "beta", "90", "gamma", "200"],
        tamper={"op": "set_claim", "path": ["selected"], "value": "gamma"},
        expected_verdict="REFUSE cert-selection-mismatch",
        note="renaming the winner does not change the argmin",
    )
    add(
        case_id="poison_selected_and_runner_up_collapsed",
        case_class="poison",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d_tamper", "latency_ms", "min", "alpha", "120", "beta", "90"],
        tamper={"op": "set_claim", "path": ["selected"], "value": "alpha"},
        expected_verdict="REFUSE cert-runner-up-is-selected",
        note="a certificate that names one option as both winner and runner-up",
    )
    add(
        case_id="poison_runner_up_relabelled",
        case_class="poison",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d_tamper", "throughput_rps", "max", "a", "1", "b", "2", "c", "3"],
        tamper={"op": "set_claim", "path": ["runner_up"], "value": "a"},
        expected_verdict="REFUSE cert-runner-up-mismatch",
    )
    add(
        case_id="poison_margin_inflated",
        case_class="poison",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d_tamper", "latency_ms", "min", "alpha", "120", "beta", "90"],
        tamper={"op": "set_claim", "path": ["margin"], "value": "9000"},
        expected_verdict="REFUSE cert-margin-mismatch",
        note="a comfortable-looking margin is recomputed, not believed",
    )
    add(
        case_id="poison_margin_forced_to_zero_by_flattening_values",
        case_class="poison",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        # The winner must sit at index 0 so that flattening the runner-up leaves
        # the engine's first-wins tie-break agreeing with the recorded
        # `selected`. Flattening the other way round refuses with
        # `cert-selection-mismatch` instead -- again caught by the generator, not
        # assumed away.
        argv=["d_tamper", "latency_ms", "min", "alpha", "90", "beta", "120"],
        tamper={"op": "set_claim", "path": ["options", 1, "value"], "value": "90"},
        expected_verdict="REFUSE cert-margin-zero",
        note="a tie reintroduced by editing an option value is still a coin flip",
    )
    add(
        case_id="poison_criterion_rewritten_to_a_value_judgment",
        case_class="poison",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d_tamper", "latency_ms", "min", "alpha", "120", "beta", "90"],
        tamper={"op": "set_claim", "path": ["criterion"], "value": "best_latency"},
        expected_verdict="REFUSE cert-value-judgment",
        note="the checker mirrors the engine's blocklist, so neither door is open",
    )
    add(
        case_id="poison_malformed_envelope_missing_witness",
        case_class="poison",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d_tamper", "latency_ms", "min", "alpha", "120", "beta", "90"],
        tamper={"op": "delete_envelope_key", "key": "witness"},
        expected_verdict="REFUSE cert-envelope-keys",
    )
    add(
        case_id="poison_value_wider_than_the_checker_admits",
        case_class="poison",
        operation_id=OP_DECISION_RANK,
        engine_command="decision-rank",
        argv=["d_wide", "queue_depth", "max", "alpha", "-" + "9" * 65, "beta", "2"],
        expected_verdict="REFUSE cert-field-shape",
        note=(
            "documented divergence: the engine admits a 65-digit magnitude the "
            "checker's canonical-integer shape does not. The checker is the "
            "stricter of the two, so nothing is admitted that should not be; "
            "recorded here so the asymmetry is visible rather than folklore"
        ),
    )

    # ----------------------------------------------------------------------
    # decision.matrix.rank.v2 -- the closed-unit lane.
    #
    # v1 stays exactly as recorded above, gap and all. Everything below is the
    # second operation, where admissibility is decided by a declared unit drawn
    # from `release/claim/unit_registry_v1.json` rather than by the criterion's
    # spelling. Note which criteria appear: `throughput_rps` cannot be expressed
    # in this lane because `rps` is not a registry unit, so the rate cases
    # declare `Hz`. That friction is the mechanism working, not a rough edge.
    # ----------------------------------------------------------------------
    add(
        case_id="positive_v2_declared_unit_min",
        case_class="positive",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2_min", "latency_ms", "ms", "min", "alpha", "120", "beta", "90"],
        note="the same argmin as v1, with the unit carried into the certificate",
    )
    add(
        case_id="positive_v2_declared_unit_max_rate",
        case_class="positive",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2_max", "request_rate", "Hz", "max", "alpha", "120", "beta", "400", "gamma", "250"],
        note="a rate ranks as Hz; `rps` is not a canonical id and would refuse",
    )
    add(
        case_id="positive_v2_ratio_unit_percent",
        case_class="positive",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2_pct", "error_rate", "percent", "min", "alpha", "7", "beta", "3"],
        note=(
            "a dimensionless ratio is admissible because `percent` still names "
            "what is counted; the bare identity `one` does not and is refused"
        ),
    )
    add(
        case_id="positive_v2_six_options_upper_bound",
        case_class="positive",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=[
            "d_v2_six", "energy_used", "kWh", "min",
            "a", "6", "b", "5", "c", "4", "d", "3", "e", "2", "f", "1",
        ],
        note="the protocol upper bound of six options holds in the v2 lane too",
    )

    add(
        case_id="refusal_v2_unit_outside_the_closed_vocabulary",
        case_class="refusal",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2", "most_elegant", "elegance", "max", "alpha", "1", "beta", "2"],
        expected_refusal="decision-unit-unknown",
        note=(
            "the criterion v1 accepts. There is no unit for elegance, so the "
            "closed vocabulary refuses it however it is spelled"
        ),
    )
    add(
        case_id="refusal_v2_unit_declared_empty",
        case_class="refusal",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2", "most_elegant", "", "max", "alpha", "1", "beta", "2"],
        expected_refusal="decision-unit-missing",
    )
    add(
        case_id="refusal_v2_unit_omitted_entirely",
        case_class="refusal",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2", "most_elegant", "max", "alpha", "1", "beta", "2"],
        expected_refusal="pack-request-arity",
        note=(
            "omitting the argument is an arity refusal rather than a unit one: "
            "with positional argv there is no slot left to be empty"
        ),
    )
    add(
        case_id="refusal_v2_route_arity_rejects_a_missing_unit",
        case_class="refusal",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2", "most_elegant", "max", "alpha", "1", "beta", "2"],
        route_only=True,
        expected_refusal="pack-request-arity",
        note="the pack's own route guard refuses before the engine is reached",
    )
    add(
        case_id="refusal_v2_leetspeak_criterion_with_a_bogus_unit",
        case_class="refusal",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2", "b3st", "elegance", "max", "alpha", "1", "beta", "2"],
        expected_refusal="decision-unit-unknown",
        note="`b3st` defeats the word list; it cannot defeat the unit set",
    )
    add(
        case_id="refusal_v2_dimensionless_identity_is_not_a_unit",
        case_class="refusal",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2", "optimal_score", "one", "max", "alpha", "1", "beta", "2"],
        expected_refusal="decision-unit-unknown",
        note=(
            "`one` is a canonical registry id and is still refused here: it is "
            "the deliberate exclusion, and this row is what proves it is live"
        ),
    )
    add(
        case_id="refusal_v2_value_judgment_survives_an_admissible_unit",
        case_class="refusal",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2", "best_score", "ms", "min", "alpha", "120", "beta", "90"],
        expected_refusal="decision-value-judgment",
        note="the v1 word list is retained as a second gate, not replaced",
    )
    add(
        case_id="refusal_v2_alias_is_not_a_canonical_unit",
        case_class="refusal",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2", "latency_ms", "millisecond", "min", "alpha", "120", "beta", "90"],
        expected_refusal="decision-unit-unknown",
        note=(
            "the registry lists `millisecond` as an alias for input "
            "canonicalisation only; this lane records what it is given, so it "
            "admits canonical ids only"
        ),
    )
    add(
        case_id="refusal_v2_unit_comparison_is_case_sensitive",
        case_class="refusal",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2", "latency_ms", "Ms", "min", "alpha", "120", "beta", "90"],
        expected_refusal="decision-unit-unknown",
        note=(
            "case matters by design: `mW` and `MW` differ by a factor of a "
            "million, so a case-insensitive match would admit the wrong unit"
        ),
    )
    add(
        case_id="refusal_v2_duplicate_label",
        case_class="refusal",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2", "latency_ms", "ms", "min", "alpha", "5", "alpha", "6"],
        expected_refusal="decision-duplicate-label",
    )
    add(
        case_id="refusal_v2_top_two_tie",
        case_class="refusal",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2", "latency_ms", "ms", "max", "alpha", "5", "beta", "5"],
        expected_refusal="decision-margin-zero",
    )
    add(
        case_id="refusal_v2_sense_unknown",
        case_class="refusal",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2", "latency_ms", "ms", "minimise", "alpha", "5", "beta", "6"],
        expected_refusal="decision-sense-unknown",
    )

    add(
        case_id="poison_v2_unit_replaced_with_a_bogus_token",
        case_class="poison",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2_tamper", "latency_ms", "ms", "min", "alpha", "120", "beta", "90"],
        tamper={"op": "set_claim", "path": ["unit"], "value": "elegance"},
        expected_verdict="REFUSE cert-unit-not-admitted",
        note="the checker holds the same closed vocabulary, so neither door opens",
    )
    add(
        case_id="poison_v2_unit_replaced_with_the_dimensionless_identity",
        case_class="poison",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2_tamper", "latency_ms", "ms", "min", "alpha", "120", "beta", "90"],
        tamper={"op": "set_claim", "path": ["unit"], "value": "one"},
        expected_verdict="REFUSE cert-unit-not-admitted",
    )
    add(
        case_id="poison_v2_unit_key_deleted",
        case_class="poison",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2_tamper", "latency_ms", "ms", "min", "alpha", "120", "beta", "90"],
        tamper={"op": "delete_claim_key", "key": "unit"},
        expected_verdict="REFUSE cert-claim-keys",
        note="a v2 certificate without a unit is not a v1 certificate",
    )
    add(
        case_id="poison_v2_criterion_rewritten_to_a_value_judgment",
        case_class="poison",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2_tamper", "latency_ms", "ms", "min", "alpha", "120", "beta", "90"],
        tamper={"op": "set_claim", "path": ["criterion"], "value": "best_latency"},
        expected_verdict="REFUSE cert-value-judgment",
    )
    add(
        case_id="poison_v2_margin_inflated",
        case_class="poison",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2_tamper", "latency_ms", "ms", "min", "alpha", "120", "beta", "90"],
        tamper={"op": "set_claim", "path": ["margin"], "value": "9000"},
        expected_verdict="REFUSE cert-margin-mismatch",
        note="the shared recomputation still bites in the v2 lane",
    )
    add(
        case_id="poison_v2_kind_downgraded_to_v1",
        case_class="poison",
        operation_id=OP_DECISION_RANK_V2,
        engine_command="decision-rank-v2",
        argv=["d_v2_tamper", "latency_ms", "ms", "min", "alpha", "120", "beta", "90"],
        tamper={"op": "set_envelope_value", "key": "kind", "value": "decision-rank"},
        expected_verdict="REFUSE cert-kind-unexpected",
        note=(
            "a v2 certificate cannot be relabelled into the v1 lane to shed the "
            "unit requirement"
        ),
    )
    return specs


PACKS: dict[str, dict[str, Any]] = {
    "programming": {
        "pack_id": PROGRAMMING_PACK,
        "specs": programming_specs,
        "certificate_prefix": TEST_EXISTS_PREFIX,
        "checker": TEST_EXISTS_CHECKER,
        "corpus_path": "tests/corpus/programming_corpus_v1.json",
        "fixtures": [
            PY_FIXTURE,
            DOCSTRING_FIXTURE,
            RAW_STRING_FIXTURE,
            LINE_COMMENT_FIXTURE,
            BLOCK_COMMENT_FIXTURE,
            CLAIM_DOC,
        ],
    },
    "decision": {
        "pack_id": DECISION_PACK,
        "specs": decision_specs,
        "certificate_prefix": DECISION_PREFIX,
        "checker": DECISION_CHECKER,
        "corpus_path": "tests/corpus/decision_corpus_v1.json",
        "fixtures": [],
    },
}


# --------------------------------------------------------------------------
# observation and freezing
# --------------------------------------------------------------------------


def observe_case(engine: Engine, pack: dict, spec: dict) -> dict:
    """Run one case against the real engine and the real checker.

    The returned row records only what was observed. Nothing here compares an
    observation to an expectation; `--self-check` and the suites do that against
    the frozen file, which is what makes a regression visible.
    """
    prefix = pack["certificate_prefix"]
    pack_id = spec.get("route_pack_id", pack["pack_id"])
    operation_id = spec.get("route_operation_id", spec["operation_id"])
    argv = list(spec["argv"])

    row: dict[str, Any] = {
        "case_id": spec["case_id"],
        "case_class": spec["case_class"],
        "operation_id": spec["operation_id"],
        "engine_command": spec["engine_command"],
        "argv": argv,
    }
    for optional in (
        "note",
        "route_only",
        "route_pack_id",
        "route_operation_id",
        "tamper",
        "expected_refusal",
        "expected_verdict",
    ):
        if optional in spec:
            row[optional] = spec[optional]

    if spec.get("route_only"):
        observed = engine.route(pack_id, operation_id, *argv)
        row["invocation"] = "pack-route"
    else:
        observed = engine.run(spec["engine_command"], *argv)
        row["invocation"] = "direct"

    row["engine"] = {
        "returncode": observed.returncode,
        "refusal_class": observed.refusal_class,
        "refusal_detail": observed.refusal_detail,
        "stdout": observed.stdout,
        "stdout_sha256": hashlib.sha256(observed.stdout.encode("utf-8")).hexdigest(),
    }

    if observed.returncode != 0:
        if spec["case_class"] != "refusal":
            raise CorpusError(
                f"{spec['case_id']}: engine refused a non-refusal case "
                f"({observed.refusal_class})"
            )
        # The spec's intent is checked against the observed class, not merely
        # recorded beside it. Without this a spec could claim to exercise
        # `prog-hex64`, trip `prog-path` instead, and freeze happily -- the
        # corpus would then be a regression witness for the wrong refusal.
        if observed.refusal_class != spec.get("expected_refusal"):
            raise CorpusError(
                f"{spec['case_id']}: expected refusal class "
                f"{spec.get('expected_refusal')!r} but the engine refused with "
                f"{observed.refusal_class!r}"
            )
        row["route_parity"] = None
        row["checker"] = None
        return row

    if spec["case_class"] == "refusal":
        raise CorpusError(f"{spec['case_id']}: engine accepted a refusal case")

    # Byte parity: a route must reproduce the direct command's stdout exactly.
    routed = engine.route(pack["pack_id"], spec["operation_id"], *argv)
    if routed.returncode != 0:
        raise CorpusError(
            f"{spec['case_id']}: route refused what the direct command accepted: "
            f"{routed.refusal_class}"
        )
    row["route_parity"] = routed.stdout == observed.stdout
    if not row["route_parity"]:
        raise CorpusError(f"{spec['case_id']}: route stdout differs from direct stdout")

    certificate = observed.certificate(prefix)
    if "tamper" in spec:
        certificate = apply_tamper(certificate, prefix, spec["tamper"])
    row["certificate"] = certificate

    if pack["checker"] == TEST_EXISTS_CHECKER:
        verdict = check_test_exists(certificate)
    else:
        verdict = check_decision(certificate)
    row["checker"] = {
        "tool": pack["checker"],
        "root": "repository",
        "returncode": verdict.returncode,
        "verdict": verdict.summary,
        "reason_class": verdict.reason_class,
    }
    default_verdict = "ACCEPT" if spec["case_class"] == "positive" else None
    expected_verdict = spec.get("expected_verdict", default_verdict)
    if verdict.summary != expected_verdict:
        raise CorpusError(
            f"{spec['case_id']}: expected verdict {expected_verdict!r} but the "
            f"checker returned {verdict.line!r}"
        )
    if spec["case_class"] == "poison" and verdict.summary == "ACCEPT":
        raise CorpusError(f"{spec['case_id']}: poison case was ACCEPTed")
    return row


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def corpus_digest(document: dict) -> str:
    """Aggregate digest over every field except the digest itself."""
    body = {key: value for key, value in document.items() if key != DIGEST_KEY}
    return hashlib.sha256(canonical_bytes(body)).hexdigest()


def build_corpus(name: str, engine: Engine) -> dict:
    pack = PACKS[name]
    rows = [observe_case(engine, pack, spec) for spec in pack["specs"]()]
    counts: dict[str, int] = {"positive": 0, "refusal": 0, "poison": 0}
    for row in rows:
        counts[row["case_class"]] += 1
    for case_class, count in counts.items():
        if count == 0:
            raise CorpusError(f"{name} corpus has no {case_class} cases; it is vacuous")
    document = {
        "schema": CORPUS_SCHEMA,
        "corpus_version": "1",
        "pack_id": pack["pack_id"],
        "generated_by": "tests/corpus/generate_pack_corpus.py",
        "authority": "anubis-safe-mode",
        "engine": {
            "anubis_pin": engine.anubis_pin,
            "entry_source_path": "jackal_calc.anb",
            "entry_source_sha256": engine.engine_source_sha256,
            "harness_mode": engine.mode,
        },
        "checker": {
            "path": pack["checker"],
            "sha256": sha256_file(pack["checker"]),
        },
        "fixtures": [
            {"path": relative, "sha256": sha256_file(relative)}
            for relative in pack["fixtures"]
        ],
        "case_counts": counts,
        "nonclaims": [
            "a_frozen_observation_is_not_a_proof_of_correctness",
            "the_refusal_classes_recorded_here_are_not_exhaustive",
            "an_accepted_certificate_says_nothing_about_the_code_it_names",
        ],
        "cases": rows,
    }
    document[DIGEST_KEY] = corpus_digest(document)
    return document


def corpus_file(name: str) -> Path:
    return ROOT / PACKS[name]["corpus_path"]


def load_corpus(name: str) -> dict:
    path = corpus_file(name)
    if not path.is_file():
        raise CorpusError(f"frozen corpus missing: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    recorded = document.get(DIGEST_KEY)
    recomputed = corpus_digest(document)
    if recorded != recomputed:
        raise CorpusError(
            f"{path.name} aggregate digest mismatch: recorded {recorded}, "
            f"recomputed {recomputed}"
        )
    if document.get("schema") != CORPUS_SCHEMA:
        raise CorpusError(f"{path.name} is not {CORPUS_SCHEMA}")
    return document


def cases_by_id(document: dict) -> dict[str, dict]:
    return {row["case_id"]: row for row in document["cases"]}


def freeze(name: str, engine: Engine) -> Path:
    document = build_corpus(name, engine)
    path = corpus_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _compare(name: str, frozen: dict, observed: dict, problems: list[str]) -> None:
    """Field-by-field comparison, so a divergence names itself."""
    frozen_rows = cases_by_id(frozen)
    observed_rows = cases_by_id(observed)
    missing = sorted(set(frozen_rows) - set(observed_rows))
    extra = sorted(set(observed_rows) - set(frozen_rows))
    if missing:
        problems.append(f"{name}: frozen cases absent from the spec list: {missing}")
    if extra:
        problems.append(f"{name}: spec cases absent from the frozen corpus: {extra}")
    for key in ("pack_id", "checker", "fixtures", "case_counts"):
        if frozen.get(key) != observed.get(key):
            problems.append(
                f"{name}: {key} drifted\n  frozen   {frozen.get(key)}\n"
                f"  observed {observed.get(key)}"
            )
    for case_id in sorted(set(frozen_rows) & set(observed_rows)):
        want, got = frozen_rows[case_id], observed_rows[case_id]
        for field in ("case_class", "argv", "invocation", "engine", "checker", "route_parity"):
            if want.get(field) != got.get(field):
                problems.append(
                    f"{name}/{case_id}: {field} drifted\n  frozen   {want.get(field)!r}\n"
                    f"  observed {got.get(field)!r}"
                )


def self_check(names: Iterable[str], engine: Engine) -> list[str]:
    problems: list[str] = []
    for name in names:
        try:
            frozen = load_corpus(name)
        except CorpusError as error:
            problems.append(str(error))
            continue
        observed = build_corpus(name, engine)
        # The harness mode is environmental, not part of what is being frozen.
        observed_body = copy.deepcopy(observed)
        observed_body["engine"]["harness_mode"] = frozen["engine"].get("harness_mode")
        observed_body[DIGEST_KEY] = corpus_digest(observed_body)
        if frozen[DIGEST_KEY] != observed_body[DIGEST_KEY]:
            problems.append(
                f"{name}: aggregate digest differs from a fresh observation "
                f"(frozen {frozen[DIGEST_KEY]}, observed {observed_body[DIGEST_KEY]})"
            )
        _compare(name, frozen, observed_body, problems)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen domain-pack corpora.")
    parser.add_argument("--freeze", action="store_true", help="rewrite the corpus files")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="re-observe every case and compare against the frozen corpus",
    )
    parser.add_argument(
        "--pack", choices=(*PACKS, "all"), default="all", help="which corpus to act on"
    )
    args = parser.parse_args(argv)
    if args.freeze == args.self_check:
        print("REFUSE corpus-mode-ambiguous: pass exactly one of --freeze or --self-check")
        return 2

    names = list(PACKS) if args.pack == "all" else [args.pack]
    try:
        engine = Engine.shared()
    except CorpusError as error:
        print(f"REFUSE corpus-engine-unavailable: {error}")
        return 2
    print(f"  harness mode {engine.mode}, pin {engine.anubis_pin}")

    if args.freeze:
        for name in names:
            try:
                path = freeze(name, engine)
            except CorpusError as error:
                print(f"REFUSE corpus-generation-failed: {name}: {error}")
                return 2
            document = json.loads(path.read_text(encoding="utf-8"))
            print(
                f"  froze {path.relative_to(ROOT)} "
                f"cases={len(document['cases'])} "
                f"counts={document['case_counts']} "
                f"digest={document[DIGEST_KEY]}"
            )
        print("FROZEN")
        return 0

    try:
        problems = self_check(names, engine)
    except CorpusError as error:
        print(f"REFUSE corpus-self-check-failed: {error}")
        return 2
    if problems:
        for problem in problems:
            print(f"  {problem}")
        print("REFUSE corpus-self-check-failed")
        return 2
    for name in names:
        document = load_corpus(name)
        print(
            f"  {name}: cases={len(document['cases'])} "
            f"counts={document['case_counts']} digest={document[DIGEST_KEY]}"
        )
    print("ACCEPT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
