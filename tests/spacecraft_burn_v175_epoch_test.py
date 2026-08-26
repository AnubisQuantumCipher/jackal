from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EPOCH = "v1.7.5"
NONCE = "spacecraft-burn-v2-publication-20260825"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


class SpacecraftBurnV175EpochTests(unittest.TestCase):
    def test_readme_marks_v175_as_published_latest_corrective_release(self):
        readme = (ROOT / "README.md").read_text()
        rendered = " ".join(readme.split())
        self.assertIn("**Published state:**", rendered)
        self.assertIn("observed public **Latest** release", rendered)
        self.assertIn(
            "https://github.com/AnubisQuantumCipher/jackal/releases/tag/v1.7.5",
            readme,
        )
        self.assertIn(
            "release/evidence/spacecraft_burn_release_readback_v175.json",
            readme,
        )
        self.assertIn("12 uploaded release asset byte identities", rendered)
        self.assertIn("11 `SHA256SUMS` payload rows", rendered)
        self.assertIn("v1.7.4 release, tag, assets", rendered)
        self.assertIn("remain immutable historical evidence", rendered)
        for stale in (
            "v1.7.5 corrective release candidate",
            "Commit-scoped status",
            "source snapshot was prepared",
            "exists only after publication",
            "only after the fresh public-download",
        ):
            self.assertNotIn(stale, rendered)

    def test_published_docs_and_immutable_tag_surfaces_are_consistent(self):
        surfaces = (
            (
                ROOT / "spacecraft_burn_cert/README.md",
                "../release/evidence/spacecraft_burn_release_readback_v175.json",
            ),
            (
                ROOT / "spacecraft_burn_cert/REPORT.md",
                "../release/evidence/spacecraft_burn_release_readback_v175.json",
            ),
        )
        release_url = (
            "https://github.com/AnubisQuantumCipher/jackal/releases/tag/v1.7.5"
        )
        for path, readback_link in surfaces:
            with self.subTest(path=str(path)):
                text = path.read_text()
                rendered = " ".join(text.split())
                self.assertIn("Published state:", rendered)
                self.assertIn("observed public Latest release", rendered)
                self.assertIn(release_url, text)
                self.assertIn(readback_link, text)
                self.assertIn(
                    "v1.7.4 release, tag, assets, and readback remain immutable "
                    "historical evidence",
                    rendered,
                )
                for stale in (
                    "Commit-scoped publication state",
                    "v1.7.5 candidate",
                    "current GitHub release state",
                    "exists only after publication",
                ):
                    self.assertNotIn(stale, rendered)

        notes = (ROOT / "release/spacecraft_burn_v175_release_notes.md").read_text()
        metadata = json.loads(
            (ROOT / "release/evidence/spacecraft_burn_release_metadata_v175.json")
            .read_text()
        )
        self.assertTrue(
            notes.startswith(
                "# JACKAL v1.7.5 - Spacecraft finite-burn certification\n"
            )
        )
        self.assertNotIn("candidate; not published", notes)
        self.assertEqual(metadata["tag"], EPOCH)
        self.assertEqual(
            metadata["title"],
            "JACKAL v1.7.5 - Spacecraft finite-burn certification",
        )

    def test_checker_proof_identity_and_workflow_use_v175_epoch(self):
        checker = (ROOT / "proofs/lean/JackalIv/Spacecraft/CertCheck.lean").read_text()
        self.assertIn(f'def spacecraftReleaseEpoch : String := "{EPOCH}"', checker)

        identity = load_module(
            ROOT / "release/tools/spacecraft_burn_proof_identity.py", "spacecraft_identity_v175"
        )
        self.assertEqual(identity.SPACECRAFT_LANE.fragment["release_epoch"], EPOCH)

        workflow = (ROOT / ".github/workflows/spacecraft-burn-proof-gate.yml").read_text()
        self.assertIn(f"RELEASE_EPOCH: {EPOCH}", workflow)
        self.assertIn(f"PUBLICATION_NONCE: {NONCE}", workflow)

    def test_current_evidence_is_bound_to_v175(self):
        receipt = json.loads(
            (ROOT / "spacecraft_burn_cert/evidence/baseline_receipt_v2.json").read_text()
        )
        identity = json.loads(
            (ROOT / "release/evidence/spacecraft_burn_proof_identity_v1.json").read_text()
        )
        self.assertEqual(receipt["formal_checker"]["epoch"], EPOCH)
        self.assertEqual(receipt["formal_checker"]["nonce"], NONCE)
        self.assertEqual(identity["fragment"]["release_epoch"], EPOCH)

    def test_current_evidence_is_bound_to_current_source_and_receipt(self):
        evidence = ROOT / "spacecraft_burn_cert/evidence"
        source_path = ROOT / "spacecraft_burn_cert/certify.py"
        receipt_path = evidence / "baseline_receipt_v2.json"
        receipt = json.loads(receipt_path.read_text())
        source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        receipt_digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        manifest = json.loads((evidence / "baseline_witness_v2.manifest.json").read_text())
        independent = json.loads((evidence / "independent_verification_v2.json").read_text())
        instrument = json.loads((evidence / "instrument_validation_v2.json").read_text())
        mutation = json.loads((evidence / "mutation_aba_v2.json").read_text())

        self.assertEqual(receipt["source_sha256"], source_digest)
        self.assertEqual(manifest["receipt_sha256"], receipt_digest)
        self.assertEqual(independent["binding"]["receipt_sha256"], receipt_digest)
        self.assertEqual(instrument["baseline_receipt_sha256"], receipt_digest)
        self.assertEqual(mutation["baseline_source_sha256"], source_digest)
        self.assertEqual(mutation["final_source_sha256"], source_digest)
        for record in mutation["mutations"]:
            with self.subTest(mutation=record["mutation"]):
                self.assertEqual(record["a_before_sha256"], source_digest)
                self.assertEqual(record["a_after_sha256"], source_digest)

    def test_report_identity_table_matches_current_v175_evidence(self):
        receipt_path = ROOT / "spacecraft_burn_cert/evidence/baseline_receipt_v2.json"
        identity_path = ROOT / "release/evidence/spacecraft_burn_proof_identity_v1.json"
        receipt = json.loads(receipt_path.read_text())
        identity = json.loads(identity_path.read_text())
        report = (ROOT / "spacecraft_burn_cert/REPORT.md").read_text()
        expected = (
            hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            receipt["formal_checker"]["checker_sha256"],
            hashlib.sha256(identity_path.read_bytes()).hexdigest(),
            identity["identity_digest_sha256"],
            receipt["formal_checker"]["witness_sha256"],
            receipt["formal_checker"]["request_digest"],
        )
        for digest in expected:
            with self.subTest(digest=digest):
                self.assertIn(f"`{digest}`", report)

    def test_v175_packager_is_new_and_v174_packager_stays_frozen(self):
        v174 = load_module(
            ROOT / "release/tools/package_spacecraft_v174.py", "spacecraft_package_v174_frozen"
        )
        v175 = load_module(
            ROOT / "release/tools/package_spacecraft_v175.py", "spacecraft_package_v175"
        )
        self.assertEqual(v174.VERSION, "v1.7.4")
        self.assertEqual(v175.VERSION, EPOCH)
        self.assertEqual(v175.CERTIFICATE_EPOCH, EPOCH)
        self.assertEqual(
            v175.ARCHIVE_NAME,
            "jackal-spacecraft-burn-v1.7.5-verifier-macos-arm64.tar.gz",
        )


if __name__ == "__main__":
    unittest.main()
