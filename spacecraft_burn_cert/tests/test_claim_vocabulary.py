from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "evidence" / "legacy-v1"
LEGACY_MANIFEST = LEGACY / "MANIFEST.sha256"


def derived_legacy_manifest() -> str:
    rows = []
    for path in sorted(LEGACY.iterdir(), key=lambda item: item.name):
        if path.name == LEGACY_MANIFEST.name:
            continue
        if not path.is_file() or path.is_symlink():
            raise AssertionError(f"unexpected legacy evidence entry: {path.name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  {path.name}\n")
    return "".join(rows)


class ClaimVocabularyTests(unittest.TestCase):
    def test_v1_evidence_is_quarantined_and_not_current(self):
        self.assertTrue((LEGACY / "baseline_receipt.json").is_file())
        self.assertFalse((ROOT / "evidence" / "baseline_receipt.json").exists())
        receipt = json.loads((LEGACY / "baseline_receipt.json").read_text())
        self.assertEqual(receipt["verdict"], "PROVED SAFE")

    def test_legacy_manifest_is_mechanically_reproducible(self):
        self.assertTrue(LEGACY_MANIFEST.is_file())
        self.assertEqual(LEGACY_MANIFEST.read_text(), derived_legacy_manifest())


if __name__ == "__main__":
    if sys.argv[1:] == ["--write-legacy-manifest"]:
        LEGACY_MANIFEST.write_text(derived_legacy_manifest(), encoding="ascii")
    else:
        unittest.main()
