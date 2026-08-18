#!/usr/bin/env python3
"""Narrow behavioral contract for the fail-closed v1.7.2 gate driver."""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "release/tools/run_gates_v172.py"
RANGE_V170 = "05c3518b836f239712f897c483a2ddadad9f544e0887b1b7bb1424a27289de8a"
REVOKED_INT_V170 = "c858e3bfc0ff2809a808170caabbf090077cb54996e76f065dbcd26ffb067d49"


def load_driver():
    spec = importlib.util.spec_from_file_location("gate_driver_v172_unit", DRIVER)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot import v1.7.2 gate driver")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GateDriverV172BehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.driver = load_driver()

    def test_archival_range_replay_and_int_revocation_are_distinct(self) -> None:
        self.assertEqual(self.driver.V170_RANGE_CHECKER_SHA256, RANGE_V170)
        self.assertEqual(
            self.driver.REVOKED_V170_INT_CHECKER_SHA256, REVOKED_INT_V170
        )
        source = DRIVER.read_text(encoding="utf-8")
        self.assertIn("jackal_cert_check_v170", source)
        self.assertIn("jackal_int_cert_check_v170", source)
        names = {name for name, _command, _timeout in self.driver.ARCHIVAL_GATES}
        self.assertEqual(
            names,
            {"archival-range-replay-v150", "archival-int-cert-revocation-v170"},
        )
        self.assertNotIn("archival-replay-v170", names)
        replay_body = source.split("def verify_archival_receipt", 1)[1].split(
            "def internal_archival_range_replay", 1
        )[0]
        self.assertIn('variant != "range"', replay_body)
        self.assertNotIn('variant == "int_cert"', replay_body)

    def test_int_revocation_requires_a_semantic_current_policy_refusal(self) -> None:
        self.assertTrue(
            self.driver.int_revocation_refused(
                1, "status=refused reason=proof-compatibility detail=revoked"
            )
        )
        self.assertFalse(self.driver.int_revocation_refused(0, "status=verified"))
        self.assertFalse(self.driver.int_revocation_refused(2, "usage: verifier"))
        source = DRIVER.read_text(encoding="utf-8")
        body = source.split("def internal_archival_int_revocation", 1)[1].split(
            "def internal(", 1
        )[0]
        self.assertIn('PACKAGE_DIR / "jackal-receipt-verify"', body)
        self.assertIn('PACKAGE_DIR / "evidence/int_cert_proof_identity_v1.json"', body)

    def test_archival_verifier_requires_all_historical_accept_markers(self) -> None:
        accepted = (
            "status=verified verdict=ACCEPT\n"
            "receipt_valid=true\n"
            "checker_verdict=ACCEPT\n"
        )
        self.assertTrue(self.driver.archival_verifier_accepts(accepted))
        for missing in accepted.splitlines():
            self.assertFalse(
                self.driver.archival_verifier_accepts(
                    accepted.replace(missing + "\n", "")
                )
            )

    def test_current_gate_inventory_contains_migrated_surfaces(self) -> None:
        names = {name for name, _command, _timeout in self.driver.CURRENT_GATES}
        required = {
            "range-ordering-contract-optimized",
            "range-ordering-aba-optimized",
            "int-premise-aba-optimized",
            "int-request-binding-v172",
            "int-request-binding-v172-optimized",
            "proof-identity-v172-contract",
            "proof-identity-v172-contract-optimized",
            "proof-compat-v172-optimized",
            "gate-driver-v172-contract",
            "gate-driver-v172-contract-optimized",
            "release-wiring-v172-contract",
            "release-wiring-v172-contract-optimized",
            "rational-receipt-output-v172",
            "rational-receipt-output-v172-optimized",
            "claim-router-output-v172",
            "claim-router-output-v172-optimized",
            "fail-closed-sweep",
            "seal-audit-receipts",
            "evidence-determinism",
            "claim-hostile",
            "claim-dogfood",
            "claim-aba",
            "int-cert-release",
            "sqrt-rat-release",
            "exp-rat-release",
            "ln-rat-release",
            "sin-rat-release",
            "cos-rat-release",
            "atan-rat-release",
            "tanh-rat-release",
            "plugin-smoke",
            "exact-verify",
        }
        self.assertTrue(required <= names, sorted(required - names))

    def test_package_gate_is_actual_build_then_fresh_extract_parity(self) -> None:
        commands = {
            name: command for name, command, _timeout in self.driver.PACKAGE_GATES
        }
        self.assertEqual(
            commands["package-v172-build"],
            ["/bin/sh", "release/build_package_v172.sh", "--build"],
        )
        self.assertIn(
            "--internal-package-fresh-extract",
            commands["package-v172-fresh-extract-parity"],
        )
        self.assertNotEqual(
            commands["package-v172-build"],
            commands["package-v172-contract"],
        )
        source = DRIVER.read_text(encoding="utf-8")
        self.assertIn("package-revoked-int-checker-present", source)
        self.assertIn("package-int-revocation-policy", source)
        self.assertIn('"plugin/hermes/jackal_hermes"), "selftest"', source)
        self.assertIn("plugin_hermes.identity_match=true", source)

    def test_package_extractor_refuses_traversal_before_writing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gate-driver-tar-test-") as raw:
            temporary = Path(raw)
            archive = temporary / "hostile.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                member = tarfile.TarInfo(
                    f"{self.driver.PACKAGE_NAME}/../../escaped"
                )
                member.size = 1
                bundle.addfile(member, io.BytesIO(b"x"))
            destination = temporary / "extract"
            destination.mkdir()
            with self.assertRaises(self.driver.GateRefusal):
                self.driver.safe_extract_package(archive, destination)
            self.assertFalse((temporary / "escaped").exists())

    def test_list_is_side_effect_free_and_names_every_context(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(DRIVER), "--list"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("manifest-v172-preflight", completed.stdout)
        self.assertIn("archival-range-replay-v150", completed.stdout)
        self.assertIn("archival-int-cert-revocation-v170", completed.stdout)
        self.assertIn("package-v172-fresh-extract-parity", completed.stdout)
        self.assertIn("manifest-v172-final", completed.stdout)

    def test_unknown_selection_refuses(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(DRIVER), "not-a-gate"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("REFUSED unknown=not-a-gate", completed.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
