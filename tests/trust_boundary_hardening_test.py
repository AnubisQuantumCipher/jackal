#!/usr/bin/env python3
"""Focused unit gates for JACKAL trust-boundary hardening."""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

if hasattr(sys, "set_int_max_str_digits"):
    sys.set_int_max_str_digits(0)

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "plugin" / "hermes" / "server.py"
sys.path.insert(0, str(SERVER.parent))


def _load_exact(name: str, path: Path) -> types.ModuleType:
    raw = path.read_bytes()
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__loader__ = None
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    return module


bundle_spec = importlib.util.spec_from_file_location("jackal_bundle_hash", SERVER.parent / "bundle_hash.py")
assert bundle_spec and bundle_spec.loader
bundle_hash = importlib.util.module_from_spec(bundle_spec)
bundle_spec.loader.exec_module(bundle_hash)
runtime_files = bundle_hash.resolve_runtime_files(SERVER.parent)
for module_name, logical_name in [
    ("release_validate", "runtime/release_validate.py"),
    ("receipt_verify", "runtime/receipt_verify.py"),
    ("formal_status_gate", "runtime/formal_status_gate.py"),
    ("gaussian_release", "runtime/gaussian_release.py"),
    ("formal_receipt", "runtime/formal_receipt.py"),
]:
    _load_exact(module_name, runtime_files[logical_name])

spec = importlib.util.spec_from_file_location("jackal_hermes_server", SERVER)
assert spec and spec.loader
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class TrustBoundaryHardeningTest(unittest.TestCase):
    def test_exact_replay_accepts_exact_decimal_arithmetic(self) -> None:
        replay = server._replay_exact_expression("0.1 + 0.2", "3/10")
        self.assertEqual(replay, {"status": "verified", "exact": "3/10", "method": "independent-fraction-replay"})

    def test_exact_replay_accepts_large_integer_power(self) -> None:
        replay = server._replay_exact_expression("2^100000", str(2**100000))
        self.assertEqual(replay, {
            "status": "verified",
            "exact": str(2**100000),
            "method": "independent-fraction-replay",
        })

    def test_exact_replay_rejects_engine_divergence(self) -> None:
        with self.assertRaises(server.PluginRefusal) as caught:
            server._replay_exact_expression("1/3 + 1/6", "2/3")
        self.assertEqual(caught.exception.reason, "exact-replay-divergence")

    def test_refusal_classifier_names_singularity(self) -> None:
        self.assertEqual(server._classify_evaluator_refusal(
            "range-bound-cert: division by an interval containing zero; fail closed"
        ), "evaluator-domain-singularity")

    def test_refusal_classifier_names_unsupported_operator(self) -> None:
        self.assertEqual(server._classify_evaluator_refusal(
            "range-bound-cert: unsupported construct 'ln'; outside the certified fragment"
        ), "evaluator-unsupported-fragment")


if __name__ == "__main__":
    unittest.main()