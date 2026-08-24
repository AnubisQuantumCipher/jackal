#!/usr/bin/env python3
"""Contract and hostile-mutation tests for the repository-wide Lean audit."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
AUDITOR_PATH = ROOT / "tools/lean_admission_audit.py"
ARTIFACT_PATH = ROOT / "release/evidence/lean_admission_audit_v173.json"


def load_auditor():
    spec = importlib.util.spec_from_file_location("lean_admission_audit", AUDITOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Lean admission auditor")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


AUDITOR = load_auditor()


def lean_is_available() -> bool:
    try:
        completed = subprocess.run(
            ["lake", "env", "lean", "--version"],
            cwd=ROOT / "proofs/lean",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


LEAN_AVAILABLE = lean_is_available()


class LeanAuditFixture:
    def __init__(self, source: str) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="jackal-lean-audit-")
        self.root = Path(self.temporary.name)
        path = self.root / "proofs/lean/Probe.lean"
        path.parent.mkdir(parents=True)
        path.write_text(source, encoding="utf-8")

    def close(self) -> None:
        self.temporary.cleanup()


@unittest.skipUnless(LEAN_AVAILABLE, "pinned Lean toolchain is unavailable")
class LeanAdmissionAuditPositiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.audit = AUDITOR.build_audit(ROOT)

    def test_inventory_is_exactly_every_tracked_lean_file(self) -> None:
        expected = sorted(
            os.fsdecode(path)
            for path in subprocess.check_output(
                ["git", "-C", str(ROOT), "ls-files", "-z", "--", "proofs/lean"],
            ).split(b"\0")
            if path.endswith(b".lean")
        )
        observed = [row["path"] for row in self.audit["source_inventory"]["files"]]
        self.assertEqual(observed, expected)
        self.assertEqual(self.audit["source_inventory"]["file_count"], len(expected))
        self.assertEqual(
            self.audit["source_inventory"]["inventory_source"], "git-ls-files"
        )
        self.assertEqual(len(observed), len(set(observed)))

    def test_repository_has_no_logical_admissions_or_axiom_declarations(self) -> None:
        policy = self.audit["source_inventory"]["construct_policy"]
        self.assertEqual(policy["forbidden_findings"], [])
        self.assertEqual(self.audit["trust_surface"]["logical_admissions"], [])
        self.assertEqual(
            self.audit["trust_surface"]["repository_axiom_declarations"], []
        )
        self.assertEqual(
            policy["allowed_findings"],
            [
                {
                    "classification": "dump-only trusted runtime mirror",
                    "construct": "implemented_by",
                    "line": 102,
                    "path": "proofs/lean/JackalIv/Correspondence.lean",
                    "source_line": "@[implemented_by Dump.parseSexpImpl]",
                },
                {
                    "classification": "dump-only trusted runtime mirror",
                    "construct": "implemented_by",
                    "line": 108,
                    "path": "proofs/lean/JackalIv/Correspondence.lean",
                    "source_line": "@[implemented_by Dump.lowerSexpImpl]",
                },
            ],
        )

    def test_all_release_theorems_have_exact_standard_axiom_surface(self) -> None:
        theorem_audit = self.audit["theorem_axiom_audit"]
        self.assertEqual(theorem_audit["theorem_count"], 27)
        names = [row["theorem"] for row in theorem_audit["theorems"]]
        self.assertEqual(len(names), len(set(names)))
        for row in theorem_audit["theorems"]:
            self.assertEqual(
                row["axioms"], ["propext", "Classical.choice", "Quot.sound"]
            )
            self.assertEqual(
                row["raw_output"],
                f"'{row['theorem']}' depends on axioms: "
                "[propext, Classical.choice, Quot.sound]",
            )

    def test_toolchain_identity_is_platform_neutral_and_exact(self) -> None:
        lean = self.audit["toolchain"]["lean"]
        self.assertEqual(
            lean,
            {
                "build_profile": "Release",
                "commit": "8c9756b28d64dab099da31a4c09229a9e6a2ef35",
                "version": "4.32.0",
            },
        )

    def test_checker_bytes_match_each_source_identity(self) -> None:
        for lane in self.audit["release_bindings"]["current_proof_identities"]:
            self.assertEqual(lane["identity_checker_sha256"], lane["checker_sha256"])
            self.assertEqual(lane["identity_checker_bytes"], lane["checker_bytes"])

    def test_lane_namespaces_have_an_explicit_mapping(self) -> None:
        mapping = self.audit["release_bindings"]["lane_identifier_mapping"]
        self.assertEqual(
            mapping["compatibility_floor_to_proof_checker"],
            {
                "int_cert": "int-cert",
                "range": "range",
                "rational_variants": "range",
            },
        )
        self.assertEqual(
            mapping["proof_checker_without_compatibility_floor"], ["gaussian"]
        )

    def test_committed_artifact_is_generated_byte_for_byte(self) -> None:
        AUDITOR.check_committed(ROOT)
        self.assertEqual(ARTIFACT_PATH.read_bytes(), AUDITOR.render_audit(ROOT))

    def test_cli_check_reports_exact_counts(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-B", str(AUDITOR_PATH), "--check", "--root", str(ROOT)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.strip(),
            "LEAN_ADMISSION_AUDIT_PASS "
            f"files={self.audit['source_inventory']['file_count']} "
            f"theorems={self.audit['theorem_axiom_audit']['theorem_count']} admissions=0",
        )


class LeanAdmissionAuditMutationTest(unittest.TestCase):
    def test_evidence_paths_must_remain_below_repository_root(self) -> None:
        for supplied in ("../outside.json", "/private/tmp/outside.json"):
            with self.subTest(supplied=supplied):
                with self.assertRaisesRegex(AUDITOR.AuditError, "escapes audit root"):
                    AUDITOR.repository_path(ROOT, supplied, "test evidence")

    def test_symlinked_evidence_path_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jackal-lean-link-") as td:
            temporary = Path(td)
            root = temporary / "root"
            outside = temporary / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "evidence.json").write_text("{}\n", encoding="utf-8")
            (root / "linked").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(AUDITOR.AuditError, "escapes audit root"):
                AUDITOR.repository_path(
                    root, "linked/evidence.json", "test evidence"
                )

    def test_finding_source_line_uses_only_lf_line_boundaries(self) -> None:
        source = "alpha\rbeta\naxiom counterfeit : False\n"
        finding = AUDITOR.finding_record(
            construct="axiom_declaration",
            relative="probe.lean",
            source=source,
            code=source,
            offset=source.index("axiom"),
        )
        self.assertEqual(finding["line"], 2)
        self.assertEqual(finding["source_line"], "axiom counterfeit : False")

    def test_release_inventory_refuses_when_git_inventory_is_unavailable(self) -> None:
        failed = subprocess.CompletedProcess(
            args=["git", "ls-files"], returncode=128, stdout=b"", stderr=b"boom"
        )
        with mock.patch.object(AUDITOR.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(AUDITOR.AuditError, "git ls-files"):
                AUDITOR.tracked_lean_paths(ROOT, require_git=True)

    def test_git_inventory_uses_nul_delimiters_for_newline_paths(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["git", "ls-files", "-z"],
            returncode=0,
            stdout=b"proofs/lean/Line\nBreak.lean\0proofs/lean/Probe.lean\0",
            stderr=b"",
        )
        with mock.patch.object(AUDITOR.subprocess, "run", return_value=completed):
            paths, source = AUDITOR.tracked_lean_paths(ROOT, require_git=True)
        self.assertEqual(
            paths,
            ["proofs/lean/Line\nBreak.lean", "proofs/lean/Probe.lean"],
        )
        self.assertEqual(source, "git-ls-files")

    def test_axiom_program_forces_nonwrapping_output(self) -> None:
        source = Path(AUDITOR_PATH).read_text(encoding="utf-8")
        self.assertIn('"set_option format.width 1000"', source)

    def test_string_escape_preserves_newline_accounting(self) -> None:
        source = 'def message := "first\\\nsecond"\naxiom counterfeit : False\n'
        masked = AUDITOR.code_without_comments_or_strings(source)
        self.assertEqual(masked.count("\n"), source.count("\n"))
        self.assertEqual(len(masked), len(source))

    def test_raw_strings_are_explicitly_refused(self) -> None:
        for source in ('def value := r"raw\\text"\n', 'def value := r#"raw"#\n'):
            with self.subTest(source=source), self.assertRaisesRegex(
                AUDITOR.AuditError, "raw strings are unsupported"
            ):
                AUDITOR.code_without_comments_or_strings(source)

    def test_command_timeout_override_is_bounded(self) -> None:
        for value in ("0", "3601", "not-a-number"):
            with self.subTest(value=value), mock.patch.dict(
                os.environ, {AUDITOR.COMMAND_TIMEOUT_ENV: value}
            ), self.assertRaisesRegex(AUDITOR.AuditError, "invalid"):
                AUDITOR.command_timeout_seconds()
        with mock.patch.dict(
            os.environ, {AUDITOR.COMMAND_TIMEOUT_ENV: "600"}
        ):
            self.assertEqual(AUDITOR.command_timeout_seconds(), 600.0)

    def test_atomic_audit_output_is_world_readable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jackal-lean-write-") as td:
            path = Path(td) / "audit.json"
            AUDITOR.write_atomic(path, b"{}\n")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)

    def test_platform_neutral_source_cli_checks_all_tracked_files(self) -> None:
        inventory = subprocess.run(
            [
                "git", "-C", str(ROOT), "ls-files", "-z", "--",
                ":(glob)proofs/lean/**/*.lean",
            ],
            capture_output=True,
            check=True,
        ).stdout
        tracked_count = sum(bool(path) for path in inventory.split(b"\0"))
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(AUDITOR_PATH),
                "--source-check",
                "--root",
                str(ROOT),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.strip(),
            f"LEAN_SOURCE_ADMISSION_PASS files={tracked_count} admissions=0",
        )

    def assert_refused(self, source: str, reason: str) -> None:
        fixture = LeanAuditFixture(source)
        try:
            with self.assertRaisesRegex(AUDITOR.AuditError, reason):
                AUDITOR.scan_sources(
                    fixture.root, ["proofs/lean/Probe.lean"]
                )
        finally:
            fixture.close()

    def test_comments_and_strings_do_not_create_findings(self) -> None:
        fixture = LeanAuditFixture(
            '-- sorry axiom unsafe @[implemented_by fake]\n'
            '/- outer admit /- nested native_decide -/ extern partial -/\n'
            'def message := "sorry axiom unsafe @[implemented_by fake]"\n'
            "def ok : Nat := 1\n"
        )
        try:
            inventory = AUDITOR.scan_sources(
                fixture.root, ["proofs/lean/Probe.lean"]
            )
            self.assertEqual(inventory["construct_policy"]["forbidden_findings"], [])
            self.assertEqual(inventory["construct_policy"]["allowed_findings"], [])
        finally:
            fixture.close()

    def test_character_literals_do_not_hide_following_declarations(self) -> None:
        self.assert_refused(
            "def doubleQuote : Char := '\"'\n"
            "axiom counterfeit : False\n",
            "axiom_declaration",
        )

    def test_character_literals_and_prime_identifiers_are_not_findings(self) -> None:
        fixture = LeanAuditFixture(
            "def apostrophe : Char := '\\''\n"
            "def angle : Char := '\\u00ab'\n"
            "def ok' : Nat := 1\n"
        )
        try:
            inventory = AUDITOR.scan_sources(
                fixture.root, ["proofs/lean/Probe.lean"]
            )
            self.assertEqual(inventory["construct_policy"]["forbidden_findings"], [])
            self.assertEqual(inventory["construct_policy"]["allowed_findings"], [])
        finally:
            fixture.close()

    def test_injected_sorry_is_rejected(self) -> None:
        self.assert_refused("theorem bad : True := by sorry\n", "forbidden.*sorry")

    def test_injected_axiom_is_rejected(self) -> None:
        self.assert_refused("axiom counterfeit : False\n", "axiom_declaration")
        self.assert_refused(
            "namespace Probe\nprotected axiom counterfeit : False\nend Probe\n",
            "axiom_declaration",
        )

    def test_other_trust_bypasses_are_rejected(self) -> None:
        mutations = {
            "admit": "theorem bad : True := by admit\n",
            "unsafe": "unsafe def bad : Nat := 0\n",
            "partial": "partial def bad : Nat -> Nat := fun n => bad n\n",
            "extern": '@[extern "bad"] opaque bad : Nat\n',
            "native_decide": "example : True := by native_decide\n",
        }
        for reason, source in mutations.items():
            with self.subTest(reason=reason):
                self.assert_refused(source, reason)

    def test_unclassified_implemented_by_is_rejected(self) -> None:
        self.assert_refused(
            "opaque spec : Nat\n"
            "def impl : Nat := 0\n"
            "@[implemented_by impl] opaque exposed : Nat\n",
            "implemented_by",
        )


if __name__ == "__main__":
    unittest.main()
