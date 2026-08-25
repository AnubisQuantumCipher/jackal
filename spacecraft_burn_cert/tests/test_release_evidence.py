from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseEvidenceTests(unittest.TestCase):
    def load_module(self):
        path = ROOT / "release_evidence.py"
        spec = importlib.util.spec_from_file_location("spacecraft_release_evidence", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def make_staging(self, module, root: Path) -> Path:
        staging = root / "staging"
        staging.mkdir()
        witness = b"canonical witness\n"
        receipt = {
            "witness": {
                "sha256": module.sha256(witness), "byte_size": len(witness),
                "branch_count": 1, "tube_count": 2, "cutoff_cell_count": 1,
            },
            "formal_checker": {"theorem": "spacecraft_burn_certified_safe"},
        }
        (staging / "baseline_witness_v2.cert").write_bytes(witness)
        (staging / "baseline_receipt_v2.json").write_bytes(
            module.canonical_json(receipt)
        )
        for name in module.JSON_NAMES[1:]:
            (staging / name).write_text("{}\n")
        return staging

    def test_install_refuses_symlink_hardlink_and_resolved_parent_output_aliases(self):
        module = self.load_module()
        for case in ("symlink", "dangling-symlink", "hardlink", "resolved-parent"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                staging = self.make_staging(module, root)
                source = staging / "baseline_receipt_v2.json"
                original = source.read_bytes()
                if case == "resolved-parent":
                    evidence = root / "evidence"
                    evidence.symlink_to(staging, target_is_directory=True)
                else:
                    evidence = root / "evidence"
                    evidence.mkdir()
                    destination = evidence / "baseline_receipt_v2.json"
                    if case == "symlink":
                        destination.symlink_to(source)
                    elif case == "dangling-symlink":
                        destination.symlink_to(root / "missing.json")
                    else:
                        os.link(source, destination)
                with self.assertRaises(RuntimeError):
                    module.install_or_check(
                        staging, check=False, evidence_dir=evidence
                    )
                self.assertEqual(source.read_bytes(), original)

    def test_atomic_release_evidence_output_completes_short_writes_and_cleans_failure(self):
        module = self.load_module()
        payload = b"release evidence" * 512
        real_write = os.write

        def short_write(descriptor, data):
            return real_write(descriptor, data[:max(1, len(data) // 4)])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "evidence.json"
            with mock.patch.object(module.os, "write", side_effect=short_write) as write:
                module.atomic_write(destination, payload)
            self.assertGreater(write.call_count, 1)
            self.assertEqual(destination.read_bytes(), payload)

            failed = root / "failed.json"
            with (
                mock.patch.object(module.os, "write", side_effect=OSError("blocked")),
                self.assertRaisesRegex(OSError, "blocked"),
            ):
                module.atomic_write(failed, payload)
            self.assertFalse(failed.exists())
            self.assertEqual(list(root.glob(".failed.json.tmp-*")), [])

    def test_check_refuses_stale_evidence_entries(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / "staging"
            evidence = root / "evidence"
            staging.mkdir()
            evidence.mkdir()
            witness = b"canonical witness\n"
            receipt = {
                "witness": {
                    "sha256": module.sha256(witness), "byte_size": len(witness),
                    "branch_count": 1, "tube_count": 2, "cutoff_cell_count": 1,
                },
                "formal_checker": {"theorem": "spacecraft_burn_certified_safe"},
            }
            (staging / "baseline_witness_v2.cert").write_bytes(witness)
            (staging / "baseline_receipt_v2.json").write_bytes(module.canonical_json(receipt))
            for name in module.JSON_NAMES[1:]:
                (staging / name).write_text("{}\n")
            module.install_or_check(staging, check=False, evidence_dir=evidence)
            (evidence / "legacy-v1").mkdir()
            module.install_or_check(staging, check=True, evidence_dir=evidence)
            (evidence / "baseline_receipt.json").write_text("stale\n")
            with self.assertRaisesRegex(RuntimeError, "unexpected:baseline_receipt.json"):
                module.install_or_check(staging, check=True, evidence_dir=evidence)

    def test_manifest_binds_untracked_witness_and_receipt(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            witness = b"canonical witness\n"
            receipt = {
                "witness": {
                    "sha256": module.sha256(witness), "byte_size": len(witness),
                    "branch_count": 1, "tube_count": 2, "cutoff_cell_count": 1,
                },
                "formal_checker": {"theorem": "spacecraft_burn_certified_safe"},
            }
            (staging / "baseline_witness_v2.cert").write_bytes(witness)
            (staging / "baseline_receipt_v2.json").write_bytes(module.canonical_json(receipt))
            for name in module.JSON_NAMES[1:]:
                (staging / name).write_text("{}\n")
            files = module.expected_files(staging)
            manifest = json.loads(files[module.MANIFEST])
            self.assertEqual(manifest["sha256"], module.sha256(witness))
            self.assertEqual(manifest["receipt_sha256"], module.sha256(module.canonical_json(receipt)))
            self.assertNotIn("baseline_witness_v2.cert", files)

    def test_optional_witness_is_installed_and_checked_when_requested(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / "staging"
            evidence = root / "evidence"
            staging.mkdir()
            witness = b"canonical witness\n"
            receipt = {
                "witness": {
                    "sha256": module.sha256(witness), "byte_size": len(witness),
                    "branch_count": 1, "tube_count": 2, "cutoff_cell_count": 1,
                },
                "formal_checker": {"theorem": "spacecraft_burn_certified_safe"},
            }
            (staging / "baseline_witness_v2.cert").write_bytes(witness)
            (staging / "baseline_receipt_v2.json").write_bytes(module.canonical_json(receipt))
            for name in module.JSON_NAMES[1:]:
                (staging / name).write_text("{}\n")
            module.install_or_check(
                staging, check=False, evidence_dir=evidence, include_witness=True
            )
            self.assertEqual((evidence / "baseline_witness_v2.cert").read_bytes(), witness)
            module.install_or_check(
                staging, check=True, evidence_dir=evidence, include_witness=True
            )
            (evidence / "baseline_witness_v2.cert").write_bytes(b"corrupt\n")
            with self.assertRaisesRegex(RuntimeError, "baseline_witness_v2.cert"):
                module.install_or_check(
                    staging, check=True, evidence_dir=evidence, include_witness=True
                )


if __name__ == "__main__":
    unittest.main()
