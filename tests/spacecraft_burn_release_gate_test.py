from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "tools" / "spacecraft_burn_release_gate.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("spacecraft_burn_release_gate", GATE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load release gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_clean_surfaces(root: Path, gate) -> None:
    for relative in gate.TEXT_TARGETS:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("publication surface\n")
    for relative in gate.JSON_TARGETS:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if relative == gate.INSTRUMENT_VALIDATION_PATH:
            candidate = {
                "verdict": "CERTIFIED SAFE",
                "verdict_qualifier": gate.MODEL_QUALIFIER,
                "producer_assurance": "candidate-only",
                "formal_checker_status": "NOT_EXECUTED",
                "evidence_classification": "rigorously interval-bounded, not formal-bounded",
            }
            formal = {
                **candidate,
                "formal_checker_status": "ACCEPT",
                "evidence_classification": "formal-bounded",
            }
            destination.write_text(json.dumps({
                "schema": "spacecraft-finite-burn-instrument-validation-v2",
                "step_refinement": {"runs": [
                    {**candidate, "step_exact": "1/16"},
                    {**formal, "step_exact": "1/32"},
                    {**candidate, "step_exact": "1/48"},
                ]},
            }))
        else:
            destination.write_text("{}\n")


class SpacecraftBurnReleaseGateTests(unittest.TestCase):
    def test_current_repository_claim_surfaces_pass(self):
        self.assertEqual(load_gate().scan(ROOT)["status"], "PASS")

    def test_scan_rejects_symlink_fifo_and_oversize_surfaces(self):
        gate = load_gate()
        cases = (
            (gate.TEXT_TARGETS[0], "invalid-text-surface", "text"),
            (gate.JSON_TARGETS[0], "invalid-json", "json"),
        )
        for relative, expected_reason, surface_type in cases:
            for mutation in ("symlink", "hardlink", "fifo", "oversize"):
                with (
                    self.subTest(
                        relative=str(relative),
                        mutation=mutation,
                    ),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    write_clean_surfaces(root, gate)
                    target = root / relative
                    target.unlink()
                    if mutation in {"symlink", "hardlink"}:
                        external = root.parent / f"{root.name}-external-{target.name}"
                        self.addCleanup(
                            lambda path=external: path.unlink(missing_ok=True)
                        )
                        external.write_text("{}\n" if surface_type == "json" else "neutral\n")
                        if mutation == "symlink":
                            target.symlink_to(external)
                        else:
                            os.link(external, target)
                    elif mutation == "fifo":
                        os.mkfifo(target)
                    elif surface_type == "json":
                        target.write_text(
                            json.dumps(
                                {"padding": "x" * gate.MAX_PUBLICATION_SURFACE_BYTES}
                            )
                        )
                    else:
                        target.write_text(
                            "x" * (gate.MAX_PUBLICATION_SURFACE_BYTES + 1)
                        )
                    findings = gate.scan(root)["findings"]
                    self.assertTrue(
                        any(
                            item["file"] == str(relative)
                            and item["reason"] == expected_reason
                            for item in findings
                        ),
                        findings,
                    )

    def test_scan_rejects_symlinked_parent_directory(self):
        gate = load_gate()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            release = root / "release"
            moved = root / "release-real"
            release.rename(moved)
            release.symlink_to(moved, target_is_directory=True)
            findings = gate.scan(root)["findings"]
        self.assertTrue(
            any(
                item["file"] == str(gate.TEXT_TARGETS[-1])
                and item["reason"] == "invalid-text-surface"
                for item in findings
            ),
            findings,
        )

    def test_scan_rejects_path_replacement_after_open_once_snapshot(self):
        gate = load_gate()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            relative = gate.TEXT_TARGETS[0]
            target = root / relative
            original = root / "original-readme"
            replaced = False

            def replace_after_snapshot(observed_relative):
                nonlocal replaced
                if observed_relative == relative and not replaced:
                    target.rename(original)
                    target.write_text("publication surface\n")
                    replaced = True

            with mock.patch.object(
                gate,
                "_after_surface_snapshot",
                side_effect=replace_after_snapshot,
                create=True,
            ):
                findings = gate.scan(root)["findings"]
        self.assertTrue(
            any(
                item["file"] == str(relative)
                and item["reason"] == "invalid-text-surface"
                for item in findings
            ),
            findings,
        )

    def test_scan_rejects_root_replacement_during_snapshot(self):
        gate = load_gate()
        with tempfile.TemporaryDirectory() as directory:
            outer = Path(directory)
            root = outer / "scan-root"
            root.mkdir()
            write_clean_surfaces(root, gate)
            moved = outer / "original-root"
            replaced = False

            def replace_root(_relative):
                nonlocal replaced
                if not replaced:
                    root.rename(moved)
                    root.mkdir()
                    replaced = True

            with mock.patch.object(
                gate,
                "_after_surface_snapshot",
                side_effect=replace_root,
            ):
                findings = gate.scan(root)["findings"]
        self.assertTrue(
            any(item["reason"] == "invalid-publication-root" for item in findings),
            findings,
        )

    def test_each_forbidden_phrase_is_detected_in_every_publication_class(self):
        gate = load_gate()
        for target in gate.TEXT_TARGETS:
            for phrase in ("PROVED SAFE", "PROVED UNSAFE", "formally proved"):
                with self.subTest(target=str(target), phrase=phrase), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    write_clean_surfaces(root, gate)
                    (root / target).write_text(phrase + "\n")
                    result = gate.scan(root)
                    self.assertEqual(result["status"], "FAIL")
                    self.assertTrue(any(item["file"] == str(target) for item in result["findings"]))

    def test_certified_safe_requires_exact_adjacent_qualifier(self):
        gate = load_gate()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            (root / gate.TEXT_TARGETS[0]).write_text("CERTIFIED SAFE\n")
            self.assertEqual(gate.scan(root)["findings"][0]["reason"], "unqualified-certified-safe")

    def test_exact_qualifier_may_wrap_without_becoming_unqualified(self):
        gate = load_gate()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            wrapped = gate.QUALIFIED_VERDICT.replace(" model,", "\nmodel,")
            self.assertNotEqual(wrapped, gate.QUALIFIED_VERDICT)
            (root / gate.TEXT_TARGETS[0]).write_text(wrapped + "\n")
            self.assertEqual(gate.scan(root)["status"], "PASS")

    def test_exact_qualifier_may_end_inside_markdown_emphasis(self):
        gate = load_gate()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            (root / gate.TEXT_TARGETS[0]).write_text("**" + gate.QUALIFIED_VERDICT + "**\n")
            self.assertEqual(gate.scan(root)["status"], "PASS")

    def test_qualified_verdict_rejects_appended_assurance_clause(self):
        gate = load_gate()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            text = gate.QUALIFIED_VERDICT + " and the physical spacecraft is safe.\n"
            (root / gate.TEXT_TARGETS[0]).write_text(text)
            result = gate.scan(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["findings"][0]["reason"], "unqualified-certified-safe")

    def test_certified_safe_detection_is_case_insensitive(self):
        gate = load_gate()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            (root / gate.TEXT_TARGETS[0]).write_text("certified safe\n")
            self.assertEqual(gate.scan(root)["status"], "FAIL")

    def test_inline_markdown_cannot_hide_unqualified_assurance(self):
        gate = load_gate()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            (root / gate.TEXT_TARGETS[0]).write_text("CERTIFIED **SAFE** for flight.\n")
            result = gate.scan(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["findings"][0]["reason"], "unqualified-certified-safe")

    def test_links_and_html_cannot_hide_unqualified_assurance(self):
        gate = load_gate()
        for claim in (
            "[CERTIFIED](https://example.invalid) SAFE for flight.\n",
            "<strong>CERTIFIED</strong> <em>SAFE</em> for flight.\n",
        ):
            with self.subTest(claim=claim), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_clean_surfaces(root, gate)
                (root / gate.TEXT_TARGETS[0]).write_text(claim)
                result = gate.scan(root)
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["findings"][0]["reason"], "unqualified-certified-safe")

    def test_multiline_and_quoted_html_tags_cannot_hide_assurance(self):
        gate = load_gate()
        claims = (
            'CERTIFIED <span\nclass="claim">SAFE',
            'PROVED <span\nclass="claim">SAFE',
            'formally <span\nclass="claim">proved',
            'CERTIFIED <span title=">">SAFE',
            'PROVED <span title=">">SAFE',
            'formally <span title=">">proved',
        )
        expected_reasons = {
            "CERTIFIED": "unqualified-certified-safe",
            "PROVED": "proved-safe",
            "formally": "formally-proved-result",
        }
        for claim in claims:
            expected_reason = expected_reasons[claim.split(maxsplit=1)[0]]
            for surface in ("text", "nested-json"):
                with (
                    self.subTest(surface=surface, claim=claim),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    write_clean_surfaces(root, gate)
                    if surface == "text":
                        (root / gate.TEXT_TARGETS[0]).write_text(claim + "\n")
                    else:
                        (root / gate.JSON_TARGETS[0]).write_text(
                            json.dumps({"nested": {"claim": claim}})
                        )
                    result = gate.scan(root)
                    self.assertEqual(result["status"], "FAIL")
                    self.assertTrue(
                        any(
                            finding["reason"] == expected_reason
                            for finding in result["findings"]
                        )
                    )

    def test_rendered_block_boundaries_and_accessible_image_text_cannot_hide_assurance(self):
        gate = load_gate()
        claims = (
            "CERTIFIED</p><p>SAFE",
            "PROVED</div><div>SAFE",
            "formally</section><section>proved",
            "![CERTIFIED](certified.png) ![SAFE](safe.png)",
            '<img alt="PROVED SAFE">',
            '<span aria-label="formally proved">neutral</span>',
        )
        for claim in claims:
            for surface in ("text", "nested-json"):
                with (
                    self.subTest(surface=surface, claim=claim),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    write_clean_surfaces(root, gate)
                    if surface == "text":
                        (root / gate.TEXT_TARGETS[0]).write_text(claim + "\n")
                    else:
                        (root / gate.JSON_TARGETS[0]).write_text(
                            json.dumps({"nested": {"claim": claim}})
                        )
                    self.assertEqual(gate.scan(root)["status"], "FAIL")

    def test_markdown_reference_and_shortcut_links_cannot_hide_assurance(self):
        gate = load_gate()
        for claim in (
            "[CERTIFIED][claim] SAFE\n\n[claim]: https://example.invalid\n",
            "[PROVED][claim] SAFE\n\n[claim]: https://example.invalid\n",
            "formally [proved][claim]\n\n[claim]: https://example.invalid\n",
            "[CERTIFIED] SAFE\n\n[CERTIFIED]: https://example.invalid\n",
            "[PROVED] SAFE\n\n[PROVED]: https://example.invalid\n",
            "formally [proved]\n\n[proved]: https://example.invalid\n",
        ):
            with self.subTest(claim=claim), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_clean_surfaces(root, gate)
                (root / gate.TEXT_TARGETS[0]).write_text(claim)
                self.assertEqual(gate.scan(root)["status"], "FAIL")

    def test_comments_entities_and_markdown_escapes_cannot_hide_assurance(self):
        gate = load_gate()
        for claim in (
            "<!-- CERTIFIED SAFE for flight. -->\n",
            "CERTIFIED&#32;SAFE for flight.\n",
            r"CERTIFIED\ SAFE for flight." + "\n",
        ):
            with self.subTest(claim=claim), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_clean_surfaces(root, gate)
                (root / gate.TEXT_TARGETS[0]).write_text(claim)
                result = gate.scan(root)
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["findings"][0]["reason"], "unqualified-certified-safe")

    def test_unicode_format_controls_cannot_hide_text_or_json_assurance(self):
        gate = load_gate()
        disguised = (
            "CERTIFIED\u200b SAFE",
            "PROVED\u200b SAFE",
            "formally\u200b proved",
            "CERTIFIED&#x200b; SAFE",
            "PROVED&#x200b; SAFE",
            "formally&#x200b; proved",
        )
        for claim in disguised:
            with self.subTest(surface="text", claim=claim), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_clean_surfaces(root, gate)
                (root / gate.TEXT_TARGETS[0]).write_text(claim + "\n")
                result = gate.scan(root)
                self.assertEqual(result["status"], "FAIL")
                self.assertTrue(
                    any(item["reason"] == "unicode-format-or-control" for item in result["findings"])
                )
            with self.subTest(surface="json", claim=claim), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_clean_surfaces(root, gate)
                (root / gate.JSON_TARGETS[0]).write_text(json.dumps({"claim": claim}))
                result = gate.scan(root)
                self.assertEqual(result["status"], "FAIL")
                self.assertTrue(
                    any(item["reason"] == "unicode-format-or-control" for item in result["findings"])
                )

    def test_unicode_compatibility_and_default_ignorables_cannot_hide_assurance(self):
        gate = load_gate()
        disguised = (
            "ＣＥＲＴＩＦＩＥＤ ＳＡＦＥ",
            "𝐂𝐄𝐑𝐓𝐈𝐅𝐈𝐄𝐃 𝐒𝐀𝐅𝐄",
            "CERTI\u034fFIED SAFE",
        )
        for claim in disguised:
            for surface in ("text", "json"):
                with self.subTest(surface=surface, claim=claim), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    write_clean_surfaces(root, gate)
                    if surface == "text":
                        (root / gate.TEXT_TARGETS[0]).write_text(claim + "\n")
                    else:
                        (root / gate.JSON_TARGETS[0]).write_text(
                            json.dumps({"claim": claim})
                        )
                    result = gate.scan(root)
                    self.assertEqual(result["status"], "FAIL")
                    self.assertTrue(
                        any(
                            item["reason"]
                            in {"unicode-format-or-control", "unqualified-certified-safe"}
                            for item in result["findings"]
                        )
                    )

    def test_unicode_visual_confusables_cannot_hide_assurance_keywords(self):
        gate = load_gate()
        for claim in (
            "C\u0415RTIFIED SAFE",
            "CERT\u0406FIED SAFE",
            "CERTIFIED S\u0391FE",
            "PR\u039fVED SAFE",
        ):
            with self.subTest(claim=claim), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_clean_surfaces(root, gate)
                (root / gate.TEXT_TARGETS[0]).write_text(claim + "\n")
                result = gate.scan(root)
                self.assertEqual(result["status"], "FAIL")
                self.assertTrue(
                    any(
                        item["reason"] == "unicode-confusable-assurance-token"
                        for item in result["findings"]
                    )
                )

    def test_arbitrary_nonword_separators_cannot_hide_assurance_phrases(self):
        gate = load_gate()
        cases = {
            "proved-safe": (
                "PROVED-SAFE",
                "PROVED/SAFE",
                "PROVED_SAFE",
                "PROVED—SAFE",
                "PROVED" + (" " * 17) + "SAFE",
                "PROVED" + ("&nbsp;" * 17) + "SAFE",
                "PROVED" + ("-" * 64) + "SAFE",
                "ＰＲＯＶＥＤ_ＳＡＦＥ",
            ),
            "formally-proved-result": (
                "formally-proved",
                "formally/proved",
                "formally_proved",
                "formally—proved",
                "formally" + (" " * 17) + "proved",
                "ｆｏｒｍａｌｌｙ_ｐｒｏｖｅｄ",
            ),
            "unqualified-certified-safe": (
                "CERTIFIED-SAFE",
                "CERTIFIED/SAFE",
                "CERTIFIED_SAFE",
                "CERTIFIED—SAFE",
                "CERTIFIED" + (" " * 17) + "SAFE",
                "ＣＥＲＴＩＦＩＥＤ_ＳＡＦＥ",
            ),
        }
        for expected_reason, claims in cases.items():
            for claim in claims:
                for surface in ("text", "nested-json"):
                    with (
                        self.subTest(
                            expected_reason=expected_reason,
                            claim=claim,
                            surface=surface,
                        ),
                        tempfile.TemporaryDirectory() as directory,
                    ):
                        root = Path(directory)
                        write_clean_surfaces(root, gate)
                        if surface == "text":
                            (root / gate.TEXT_TARGETS[0]).write_text(claim + "\n")
                        else:
                            (root / gate.JSON_TARGETS[0]).write_text(
                                json.dumps({"nested": {"claim": claim}})
                            )
                        result = gate.scan(root)
                        self.assertEqual(result["status"], "FAIL")
                        self.assertTrue(
                            any(
                                item["reason"] == expected_reason
                                for item in result["findings"]
                            ),
                            result["findings"],
                        )

    def test_json_object_keys_are_claim_scanned(self):
        gate = load_gate()
        cases = (
            ("PROVED SAFE", "proved-safe"),
            ("CERTIFIED SAFE", "unqualified-certified-safe"),
            ("formally proved", "formally-proved-result"),
        )
        for claim, expected_reason in cases:
            with (
                self.subTest(claim=claim),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                write_clean_surfaces(root, gate)
                (root / gate.JSON_TARGETS[0]).write_text(
                    json.dumps({"nested": {claim: False}})
                )
                findings = gate.scan(root)["findings"]
                self.assertTrue(
                    any(
                        item["reason"] == expected_reason
                        and item.get("json_path", "").endswith("#key")
                        for item in findings
                    ),
                    findings,
                )

    def test_html_comments_cannot_split_assurance_tokens(self):
        gate = load_gate()
        for claim in (
            "CERTIFIED <!-- decoy --> SAFE",
            "PROVED <!-- decoy --> SAFE",
            "formally <!-- decoy --> proved",
        ):
            with self.subTest(claim=claim), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_clean_surfaces(root, gate)
                (root / gate.TEXT_TARGETS[0]).write_text(claim + "\n")
                self.assertEqual(gate.scan(root)["status"], "FAIL")

    def test_rendered_line_breaks_cannot_split_assurance_tokens(self):
        gate = load_gate()
        for claim in (
            "CERTIFIED\\\nSAFE",
            "PROVED\\\nSAFE",
            "formally\\\nproved",
            "CERTIFIED<br>SAFE",
            "PROVED<br/>SAFE",
            "formally<BR />proved",
        ):
            with self.subTest(claim=claim), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_clean_surfaces(root, gate)
                (root / gate.TEXT_TARGETS[0]).write_text(claim + "\n")
                self.assertEqual(gate.scan(root)["status"], "FAIL")

    def test_current_json_evidence_is_in_the_gated_surface(self):
        gate = load_gate()
        self.assertIn(
            Path("spacecraft_burn_cert/evidence/instrument_validation_v2.json"),
            gate.JSON_TARGETS,
        )
        self.assertIn(
            Path("spacecraft_burn_cert/evidence/baseline_receipt_v2.json"),
            gate.JSON_TARGETS,
        )
        self.assertIn(
            Path("release/evidence/spacecraft_burn_release_readback_v174.json"),
            gate.JSON_TARGETS,
        )
        self.assertIn(
            Path("release/evidence/spacecraft_burn_review_clearance_v175.json"),
            gate.JSON_TARGETS,
        )

    def test_frozen_github_release_metadata_and_notes_are_gated(self):
        gate = load_gate()
        expected = (
            (
                Path("release/spacecraft_burn_v175_release_notes.md"),
                gate.TEXT_TARGETS,
            ),
            (
                Path("release/evidence/spacecraft_burn_release_metadata_v175.json"),
                gate.JSON_TARGETS,
            ),
        )
        for path, targets in expected:
            with self.subTest(path=path):
                self.assertIn(path, targets)

    def test_structured_verdict_requires_qualifier_and_assurance(self):
        gate = load_gate()
        target = Path("spacecraft_burn_cert/evidence/instrument_validation_v2.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            (root / target).write_text(json.dumps({
                "schema": "spacecraft-finite-burn-instrument-validation-v2",
                "step_refinement": {"runs": [{"verdict": "CERTIFIED SAFE"}]},
            }))
            result = gate.scan(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any(item["reason"] == "incomplete-structured-assurance" for item in result["findings"])
            )

    def test_baseline_receipt_requires_formal_checker_accept(self):
        gate = load_gate()
        target = Path("spacecraft_burn_cert/evidence/baseline_receipt_v2.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            (root / target).write_text(json.dumps({
                "schema": "spacecraft-finite-burn-formal-receipt-v2",
                "verdict": "CERTIFIED SAFE",
                "verdict_qualifier": gate.MODEL_QUALIFIER,
                "producer_assurance": "candidate-only",
                "formal_checker_status": "NOT_EXECUTED",
                "evidence_classification": {
                    "overall": "rigorously interval-bounded, not formal-bounded"
                },
            }))
            result = gate.scan(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any(item["reason"] == "incomplete-structured-assurance" for item in result["findings"])
            )

    def test_qualified_text_cannot_bypass_structured_verdict_schema(self):
        gate = load_gate()
        target = Path("spacecraft_burn_cert/request_v2.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            (root / target).write_text(json.dumps({"verdict": gate.QUALIFIED_VERDICT}))
            result = gate.scan(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any(item["reason"] == "noncanonical-structured-verdict" for item in result["findings"])
            )

    def test_structured_candidate_and_formal_verdicts_are_distinguished(self):
        gate = load_gate()
        target = Path("spacecraft_burn_cert/evidence/instrument_validation_v2.json")
        candidate = {
            "step_exact": "1/16",
            "verdict": "CERTIFIED SAFE",
            "verdict_qualifier": gate.MODEL_QUALIFIER,
            "producer_assurance": "candidate-only",
            "formal_checker_status": "NOT_EXECUTED",
            "evidence_classification": "rigorously interval-bounded, not formal-bounded",
        }
        formal = {
            "step_exact": "1/32",
            "verdict": "CERTIFIED SAFE",
            "verdict_qualifier": gate.MODEL_QUALIFIER,
            "producer_assurance": "candidate-only",
            "formal_checker_status": "ACCEPT",
            "evidence_classification": "formal-bounded",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            (root / target).write_text(json.dumps({
                "schema": "spacecraft-finite-burn-instrument-validation-v2",
                "step_refinement": {
                    "runs": [candidate, formal, {**candidate, "step_exact": "1/48"}]
                },
            }))
            self.assertEqual(gate.scan(root)["status"], "PASS")

    def test_structured_formal_status_belongs_only_to_baseline_step(self):
        gate = load_gate()
        target = Path("spacecraft_burn_cert/evidence/instrument_validation_v2.json")
        candidate = {
            "step_exact": "1/32",
            "verdict": "CERTIFIED SAFE",
            "verdict_qualifier": gate.MODEL_QUALIFIER,
            "producer_assurance": "candidate-only",
            "formal_checker_status": "NOT_EXECUTED",
            "evidence_classification": "rigorously interval-bounded, not formal-bounded",
        }
        formal = {
            **candidate,
            "step_exact": "1/16",
            "formal_checker_status": "ACCEPT",
            "evidence_classification": "formal-bounded",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            (root / target).write_text(json.dumps({
                "schema": "spacecraft-finite-burn-instrument-validation-v2",
                "step_refinement": {
                    "runs": [formal, candidate, {**candidate, "step_exact": "1/48"}]
                },
            }))
            result = gate.scan(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any(
                    item["reason"] == "invalid-refinement-assurance-layout"
                    for item in result["findings"]
                )
            )

    def test_structured_refinement_requires_all_three_expected_steps(self):
        gate = load_gate()
        target = Path("spacecraft_burn_cert/evidence/instrument_validation_v2.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            (root / target).write_text(json.dumps({
                "schema": "spacecraft-finite-burn-instrument-validation-v2",
                "step_refinement": {"runs": []},
            }))
            result = gate.scan(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any(
                    item["reason"] == "invalid-refinement-assurance-layout"
                    for item in result["findings"]
                )
            )

    def test_structured_verdict_is_rejected_outside_known_schema_location(self):
        gate = load_gate()
        target = Path("spacecraft_burn_cert/evidence/instrument_validation_v2.json")
        record = {
            "verdict": "CERTIFIED SAFE",
            "verdict_qualifier": gate.MODEL_QUALIFIER,
            "producer_assurance": "candidate-only",
            "formal_checker_status": "ACCEPT",
            "evidence_classification": "formal-bounded",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            (root / target).write_text(json.dumps({"schema": "wrong", "record": record}))
            result = gate.scan(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any(item["reason"] == "unrecognized-structured-verdict" for item in result["findings"])
            )

    def test_duplicate_json_keys_are_rejected(self):
        gate = load_gate()
        target = gate.JSON_TARGETS[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            (root / target).write_text('{"schema":"one","schema":"two"}\n')
            result = gate.scan(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any(item["reason"] == "duplicate-json-key" for item in result["findings"]))

    def test_generated_instrument_file_can_be_gated_independently(self):
        gate = load_gate()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instrument_validation_v2.json"
            path.write_text(json.dumps({
                "schema": "spacecraft-finite-burn-instrument-validation-v2",
                "step_refinement": {"runs": [{"verdict": "CERTIFIED SAFE"}]},
            }))
            result = gate.scan_instrument_validation(path)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any(item["reason"] == "incomplete-structured-assurance" for item in result["findings"])
            )

    def test_instrument_cli_preserves_lexical_symlink_for_reader_refusal(self):
        gate = load_gate()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "instrument.json"
            target.write_text("{}\n")
            link = root / "instrument-link.json"
            link.symlink_to(target)
            result = {
                "status": "FAIL",
                "surface_count": 1,
                "forbidden_current_surface_count": 1,
                "findings": [{"reason": "invalid-json"}],
            }
            with (
                mock.patch.object(
                    gate,
                    "scan_instrument_validation",
                    return_value=result,
                ) as scan,
                mock.patch("builtins.print"),
            ):
                status = gate.main(["--instrument-validation", str(link)])
        self.assertEqual(status, 2)
        scan.assert_called_once_with(link)

    def test_generated_instrument_file_requires_exact_schema(self):
        gate = load_gate()
        for payload in ({}, {"schema": "wrong"}):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "instrument_validation_v2.json"
                path.write_text(json.dumps(payload))
                result = gate.scan_instrument_validation(path)
                self.assertEqual(result["status"], "FAIL")
                self.assertTrue(
                    any(item["reason"] == "invalid-instrument-schema" for item in result["findings"])
                )

    def test_forbidden_claim_inside_json_is_detected(self):
        gate = load_gate()
        target = gate.JSON_TARGETS[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_clean_surfaces(root, gate)
            (root / target).write_text('{"claim":"PROVED SAFE"}\n')
            result = gate.scan(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any(item["reason"] == "proved-safe" for item in result["findings"]))


if __name__ == "__main__":
    unittest.main()
