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
    def test_readme_marks_v175_as_commit_scoped_corrective_candidate(self):
        readme = (ROOT / "README.md").read_text()
        rendered = " ".join(readme.split())
        self.assertIn("v1.7.5 corrective release candidate", rendered)
        self.assertIn("Commit-scoped status", rendered)
        self.assertIn("source snapshot was prepared", rendered)
        self.assertIn("current GitHub publication state", rendered)
        self.assertIn(
            "v1.7.4 should not be used as the publication-grade verifier bundle",
            rendered,
        )
        self.assertIn("v1.7.4 tag full-certificate campaign was cancelled", rendered)
        self.assertIn("PR and master-branch hosted gates passed", rendered)

    def test_immutable_tag_surfaces_do_not_encode_mutable_unpublished_state(self):
        root_readme = (ROOT / "README.md").read_text()
        certificate_readme = (ROOT / "spacecraft_burn_cert/README.md").read_text()
        report = (ROOT / "spacecraft_burn_cert/REPORT.md").read_text()
        self.assertNotIn("not yet published", root_readme)
        for surface in (certificate_readme, report):
            with self.subTest(surface=surface[:40]):
                rendered = " ".join(surface.split())
                self.assertIn("Commit-scoped publication state", rendered)
                self.assertIn("current GitHub release state", rendered)
                self.assertNotIn("candidate; not published", rendered)

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
