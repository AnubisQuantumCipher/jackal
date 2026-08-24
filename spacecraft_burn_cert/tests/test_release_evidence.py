from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
