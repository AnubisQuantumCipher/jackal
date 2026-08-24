from __future__ import annotations

import importlib.util
import tarfile
import unittest
from io import BytesIO
import json
import hashlib
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "release/tools/package_spacecraft_v174.py"


def load_packager():
    spec = importlib.util.spec_from_file_location("spacecraft_v174_packager", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load release packager")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SpacecraftReleasePackageTests(unittest.TestCase):
    def test_staged_auxiliary_evidence_must_match_committed_digests(self):
        package = load_packager()
        names = package.AUXILIARY_EVIDENCE_NAMES
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            expected = {}
            for name in names:
                data = ("bound-" + name).encode()
                (staging / name).write_bytes(data)
                expected[name] = hashlib.sha256(data).hexdigest()
            loaded = package.validated_staged_evidence(staging, expected)
            self.assertEqual(set(loaded), set(names))
            (staging / names[0]).write_bytes(b"mutated")
            with self.assertRaisesRegex(RuntimeError, "staged evidence digest mismatch"):
                package.validated_staged_evidence(staging, expected)

    def test_checker_binding_must_match_packaged_witness(self):
        package = load_packager()
        witness = b"witness"
        receipt = {
            "witness": {"sha256": hashlib.sha256(witness).hexdigest()},
            "formal_checker": {"witness_sha256": "0" * 64},
        }
        with self.assertRaisesRegex(RuntimeError, "checker-bound witness digest"):
            package.validate_witness_digests(witness, receipt)

    def test_generated_claim_gate_rejects_unqualified_assurance(self):
        package = load_packager()
        with self.assertRaisesRegex(RuntimeError, "unqualified assurance"):
            package.assert_model_conditional_claims(b"CERTIFIED SAFE for the spacecraft.\n")
        with self.assertRaisesRegex(RuntimeError, "unqualified assurance"):
            package.assert_model_conditional_claims(b"CERTIFIED **SAFE** for the spacecraft.\n")

    def test_source_closure_rejects_paths_outside_lean_tree(self):
        package = load_packager()
        with self.assertRaisesRegex(RuntimeError, "invalid source path"):
            package.source_closure({"source_closure": {"files": [{"path": "release/x.lean"}]}})

    def test_source_closure_rejects_bytes_not_bound_by_identity(self):
        package = load_packager()
        identity = json.loads(package.IDENTITY.read_text())
        identity["source_closure"]["files"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "source binding mismatch"):
            package.source_closure(identity)

    def test_deterministic_archive_has_normalized_metadata_and_modes(self):
        package = load_packager()
        entries = {"z/file": (b"z", 0o644), "a/checker": (b"x", 0o755)}
        first = package.deterministic_tar_gz(entries)
        second = package.deterministic_tar_gz(entries)
        self.assertEqual(first, second)
        with tarfile.open(fileobj=BytesIO(first), mode="r:gz") as archive:
            members = archive.getmembers()
            self.assertEqual([member.name for member in members], ["a/checker", "z/file"])
            self.assertTrue(all(member.mtime == 0 and member.uid == 0 and member.gid == 0 for member in members))
            self.assertEqual(
                {member.name: member.mode for member in members},
                {"a/checker": 0o755, "z/file": 0o644},
            )

    def test_verification_instructions_preserve_model_qualifier(self):
        package = load_packager()
        binding = {
            "request_digest": "f" * 64,
            "model_id": "model-from-receipt",
            "epoch": "v1.7.4",
            "nonce": "nonce-from-receipt",
        }
        text = package.verification_text(
            "a" * 40, "b" * 64, "c" * 64, "d" * 64, "e" * 64, binding
        ).decode()
        self.assertIn("CERTIFIED SAFE under the stated finite-burn ODE model", text)
        self.assertIn("does not establish physical-model adequacy", text)
        self.assertIn("`" + binding["request_digest"] + "`", text)
        self.assertIn("`" + binding["nonce"] + "`", text)


if __name__ == "__main__":
    unittest.main()
