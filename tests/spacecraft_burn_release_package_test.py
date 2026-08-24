from __future__ import annotations

import importlib.util
import tarfile
import unittest
from io import BytesIO
from pathlib import Path


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
            self.assertEqual(members[0].mode, 0o755)

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
