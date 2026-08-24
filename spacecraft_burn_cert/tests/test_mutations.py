from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "mutation_aba.py"


def load_harness(testcase: unittest.TestCase):
    if not HARNESS.is_file():
        testcase.fail("mutation_aba.py is missing")
    spec = importlib.util.spec_from_file_location("spacecraft_mutations", HARNESS)
    if spec is None or spec.loader is None:
        testcase.fail("mutation_aba.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MutationHarnessTests(unittest.TestCase):
    def test_catalog_contains_exactly_the_six_required_mutations(self):
        harness = load_harness(self)
        self.assertEqual(
            set(harness.MUTATIONS),
            {
                "meters_as_kilometers",
                "frozen_mass",
                "periapsis_instead_of_apoapsis",
                "double_kinetic_energy",
                "center_only",
                "round_margin_upward",
            },
        )

    def test_hash_only_cycle_restores_exact_original_bytes(self):
        harness = load_harness(self)
        result = harness.hash_only_cycle("round_margin_upward")
        self.assertNotEqual(result["a_before_sha256"], result["b_sha256"])
        self.assertEqual(result["a_before_sha256"], result["a_after_sha256"])
        self.assertTrue(result["restored"])


if __name__ == "__main__":
    unittest.main()
