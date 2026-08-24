from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "tools" / "spacecraft_burn_release_gate.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("spacecraft_burn_release_gate", GATE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load release gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SpacecraftBurnReleaseGateTests(unittest.TestCase):
    def test_current_repository_claim_surfaces_pass(self):
        self.assertEqual(load_gate().scan(ROOT)["status"], "PASS")

    def test_each_forbidden_phrase_is_detected_in_every_publication_class(self):
        gate = load_gate()
        for target in gate.TARGETS:
            for phrase in ("PROVED SAFE", "PROVED UNSAFE", "formally proved"):
                with self.subTest(target=str(target), phrase=phrase), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    for relative in gate.TARGETS:
                        destination = root / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_text("publication surface\n")
                    (root / target).write_text(phrase + "\n")
                    result = gate.scan(root)
                    self.assertEqual(result["status"], "FAIL")
                    self.assertTrue(any(item["file"] == str(target) for item in result["findings"]))

    def test_certified_safe_requires_exact_adjacent_qualifier(self):
        gate = load_gate()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in gate.TARGETS:
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text("publication surface\n")
            (root / gate.TARGETS[0]).write_text("CERTIFIED SAFE\n")
            self.assertEqual(gate.scan(root)["findings"][0]["reason"], "unqualified-certified-safe")

    def test_exact_qualifier_may_wrap_without_becoming_unqualified(self):
        gate = load_gate()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in gate.TARGETS:
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text("publication surface\n")
            wrapped = gate.QUALIFIED_VERDICT.replace(" model,", "\nmodel,")
            (root / gate.TARGETS[0]).write_text(wrapped + "\n")
            self.assertEqual(gate.scan(root)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
