#!/usr/bin/env python3
"""Static and dry-plan contract for the additive v1.7.2 release wiring."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPIN = ROOT / "release" / "tools" / "repin_v172.py"
GATES = ROOT / "release" / "tools" / "run_gates_v172.py"
MANIFEST = ROOT / "release" / "MANIFEST.sha256"
COMPILER = Path("/Users/sicarii/anubis-lang/vm/pins/anubis-a733565f237d")
COMPILER_SHA256 = (
    "a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2"
)
V170_EVALUATOR_SHA256 = (
    "20b80827d3c5c2a5d0d5d6f5a84c692f230fb0f55b9c7d1fcad02a1d0b3a1083"
)
HERMES_SERVER = ROOT / "plugin/hermes/server.py"
HERMES_TOOLS = ROOT / "plugin/hermes/tools.json"
PLUGIN_SMOKE = ROOT / "tests/plugin_smoke.py"
CERT_MUTATIONS = ROOT / "tests/cert_mutations_11.py"
CLAIM_ROUTER = ROOT / "tools/claim_router.py"
CLAIM_VERIFY_WRAPPER = ROOT / "jackal-claim-verify"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def row_map(rows: list[str]) -> dict[str, list[str]]:
    return {
        row.split()[0]: row.split()
        for row in rows
        if row and not row.startswith("#")
    }


class RepinV172ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(REPIN.is_file(), f"missing v1.7.2 repin plan: {REPIN}")
        self.module = load_module(REPIN, "repin_v172_contract")

    def test_plan_pins_current_closed_premise_assets(self) -> None:
        rows = self.module.build_rows()
        self.assertTrue(rows[0].startswith("# JACKAL v1.7.2 "))
        mapped = row_map(rows)
        expected_files = {
            "checker": (
                ROOT / "proofs/lean/.lake/build/bin/jackal_cert_check",
                "jackal_cert_check",
            ),
            "range-proof-identity": (
                ROOT / "release/evidence/range_proof_identity_v172.json",
                "release/evidence/range_proof_identity_v172.json",
            ),
            "int-cert-checker": (
                ROOT / "proofs/lean/.lake/build/bin/jackal_int_cert_check",
                "jackal_int_cert_check",
            ),
            "int-cert-proof-identity": (
                ROOT / "release/evidence/int_cert_proof_identity_v172.json",
                "release/evidence/int_cert_proof_identity_v172.json",
            ),
            "compatibility-floor": (
                ROOT / "release/compat/v172_floor.json",
                "release/compat/v172_floor.json",
            ),
            "range-ordering-aba": (
                ROOT / "release/evidence/range_ordering_aba_v172.json",
                "release/evidence/range_ordering_aba_v172.json",
            ),
            "int-cert-premise-aba": (
                ROOT / "release/evidence/int_cert_premise_aba_v172.json",
                "release/evidence/int_cert_premise_aba_v172.json",
            ),
        }
        for label, (path, display) in expected_files.items():
            self.assertIn(label, mapped)
            self.assertEqual(mapped[label][1], display)
            self.assertEqual(mapped[label][-1], sha256(path))

        self.assertEqual(
            mapped["range-proof-digest"][1],
            self.module.identity_digest(
                ROOT / "release/evidence/range_proof_identity_v172.json"
            ),
        )
        self.assertEqual(
            mapped["int-cert-proof-digest"][1],
            self.module.identity_digest(
                ROOT / "release/evidence/int_cert_proof_identity_v172.json"
            ),
        )

    def test_plan_preserves_unchanged_v170_lanes(self) -> None:
        v170 = load_module(
            ROOT / "release/tools/repin_v170.py", "repin_v170_reference"
        )
        old = row_map(v170.build_rows())
        new = row_map(self.module.build_rows())
        intentionally_changed = {
            "checker",
            "range-proof-identity",
            "range-proof-digest",
            "int-cert-checker",
            "int-cert-proof-identity",
            "int-cert-proof-digest",
        }
        for label, row in old.items():
            if label not in intentionally_changed:
                self.assertEqual(new[label], row, label)

    def test_v170_evaluator_stays_historical_while_current_row_tracks_disk(self) -> None:
        review = json.loads(
            (ROOT / "release/evidence/release_review_v170.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            review["identities"]["evaluator_sha256"], V170_EVALUATOR_SHA256
        )
        current = sha256(ROOT / "jackal-native")
        self.assertNotEqual(current, V170_EVALUATOR_SHA256)
        mapped = row_map(self.module.build_rows())
        self.assertEqual(mapped["evaluator"][-1], current)

    def test_compiler_authority_is_exact_and_immutable(self) -> None:
        self.assertEqual(self.module.COMPILER_PATH, COMPILER)
        self.assertEqual(self.module.COMPILER_SHA256, COMPILER_SHA256)
        self.assertEqual(self.module.validate_compiler(), COMPILER_SHA256)
        source = REPIN.read_text(encoding="utf-8")
        self.assertNotIn("target/release", source)
        mapped = row_map(self.module.build_rows())
        self.assertEqual(
            mapped["compiler_pin"],
            ["compiler_pin", "anubis-a733565f237d", COMPILER_SHA256],
        )

    def test_v2_identity_compatibility_and_aba_bindings_are_cross_checked(self) -> None:
        self.assertTrue(
            hasattr(self.module, "validate_v172_contract"),
            "repin plan must semantically cross-check its pinned records",
        )
        report = self.module.validate_v172_contract()
        self.assertEqual(report["release_epoch"], "v1.7.2")
        self.assertEqual(
            report["range_checker_sha256"],
            sha256(ROOT / "proofs/lean/.lake/build/bin/jackal_cert_check"),
        )
        self.assertEqual(
            report["int_cert_checker_sha256"],
            sha256(ROOT / "proofs/lean/.lake/build/bin/jackal_int_cert_check"),
        )
        self.assertEqual(report["range_aba_status"], "passed")
        self.assertEqual(report["int_cert_aba_status"], "passed")

    def test_plan_mode_does_not_modify_repository_manifest(self) -> None:
        before = MANIFEST.read_bytes()
        completed = subprocess.run(
            [sys.executable, str(REPIN), "--plan"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.assertIn(b"# JACKAL v1.7.2", completed.stdout)
        self.assertEqual(MANIFEST.read_bytes(), before)


class GateDriverV172ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(GATES.is_file(), f"missing v1.7.2 gate driver: {GATES}")
        self.module = load_module(GATES, "run_gates_v172_contract")

    def test_v172_driver_has_no_live_v170_prefix(self) -> None:
        source = GATES.read_text(encoding="utf-8")
        self.assertNotIn("run_gates_v170", source)
        self.assertNotIn("GATES_V170", source)
        self.assertNotIn("unchanged prefix", source.lower())

    def test_v172_gate_sequence_separates_current_archive_and_package(self) -> None:
        names = [name for name, _argv, _timeout in self.module.GATES]
        self.assertEqual(names[0], "dependency-toolchain-preflight")
        self.assertEqual(names[1], "manifest-v172-preflight")
        self.assertLess(names.index("lake-build-current"), names.index("engine-self-test"))
        self.assertIn("archival-range-replay-v150", names)
        self.assertIn("archival-int-cert-revocation-v170", names)
        self.assertNotIn("archival-replay-v170", names)
        self.assertIn("package-v172-build", names)
        self.assertIn("package-v172-fresh-extract-parity", names)
        self.assertEqual(names[-1], "manifest-v172-final")
        self.assertNotIn("proof-identity-range", names)
        self.assertNotIn("proof-identity-int-cert", names)
        self.assertNotIn("claim-package-parity", names)

        commands = {name: argv for name, argv, _timeout in self.module.GATES}
        self.assertEqual(
            commands["proof-compat-v172-optimized"][:2],
            [sys.executable, "-O"],
        )
        self.assertIn(
            "JackalIv.IntCertPremiseContract",
            commands["lake-build-current"],
        )
        self.assertIn(
            "JackalIv.CertRequestOrderingContract",
            commands["lake-build-current"],
        )
        self.assertEqual(
            commands["manifest-v172-preflight"],
            [sys.executable, "release/tools/repin_v172.py", "--check"],
        )
        self.assertEqual(
            commands["manifest-v172-final"],
            commands["manifest-v172-preflight"],
        )

    def test_gate_success_is_refused_when_output_reports_a_skip(self) -> None:
        for output in (
            "SKIPPED-manifest-pending",
            "NOT-EXECUTED-manifest-pending",
            "SKIP oracle-containment",
            '{"verdict":"ORACLE_SKIP"}',
        ):
            self.assertTrue(self.module.skip_markers(output), output)
        self.assertEqual(self.module.skip_markers("ORACLE_SKIP=0\nVERDICT: PASS"), [])

    def test_release_wiring_never_uses_mutable_compiler_output(self) -> None:
        source = GATES.read_text(encoding="utf-8")
        self.assertNotIn("target/release", source)

    def test_preflight_pins_archival_range_inventory_by_digest(self) -> None:
        """Blocker E: the internal preflight must ``require_digest`` on the
        installed v1.7.0 historical coverage inventory, not only the checker.
        A missing inventory pin lets a stale/tampered inventory sneak into
        archival replay evidence undetected."""
        source = GATES.read_text(encoding="utf-8")
        preflight = source.split("def internal_preflight() -> None:", 1)[1]
        preflight = preflight.split("\ndef ", 1)[0]
        self.assertIn("V170_COVERAGE_INVENTORY_SHA256", preflight,
                      "preflight must reference the archival inventory SHA")
        self.assertIn('runtime / "formal_coverage_inventory.json"', preflight,
                      "preflight must pin runtime archival inventory bytes")
        self.assertIn("archival-range-inventory-dependency", preflight,
                      "preflight must label the archival inventory pin")
        self.assertIn("archival_range_inventory_sha256=", preflight,
                      "preflight PASS line must echo the pinned inventory SHA")

    def test_fresh_extract_pins_archival_checker_and_inventory_bytes(
            self) -> None:
        """Blocker E: the fresh-extract gate must ``require_digest`` on the
        extracted archival checker AND archival inventory directly, so a
        package with only a matching MANIFEST string still refuses when the
        packaged bytes were substituted."""
        source = GATES.read_text(encoding="utf-8")
        fresh = source.split(
            "def internal_package_fresh_extract() -> None:", 1)[1]
        fresh = fresh.split("\ndef ", 1)[0]
        self.assertIn('extracted / "jackal_cert_check_v170"', fresh,
                      "fresh-extract must digest-pin the packaged archival "
                      "checker bytes")
        self.assertIn("package-archival-range-checker", fresh,
                      "fresh-extract must label the archival checker pin")
        self.assertIn(
            'extracted / "evidence/formal_coverage_inventory_v170.json"',
            fresh,
            "fresh-extract must digest-pin the packaged archival inventory")
        self.assertIn("package-archival-range-inventory", fresh,
                      "fresh-extract must label the archival inventory pin")
        self.assertIn("package-current-archival-inventory-collision", fresh,
                      "fresh-extract must refuse a current inventory whose "
                      "bytes coincide with the archival digest — current and "
                      "archival tuples must remain separable")


class HermesV172ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = HERMES_SERVER.read_text(encoding="utf-8")
        self.catalog = json.loads(HERMES_TOOLS.read_text(encoding="utf-8"))

    def test_current_repo_layout_selects_v2_identity_records(self) -> None:
        self.assertIn(
            'ROOT / "release/evidence/range_proof_identity_v172.json"',
            self.source,
        )
        self.assertIn(
            'ROOT / "release/evidence/int_cert_proof_identity_v172.json"',
            self.source,
        )
        runtime = self.catalog["runtime_files"]
        self.assertEqual(
            runtime["runtime/range_proof_identity.json"][0],
            "../../release/evidence/range_proof_identity_v172.json",
        )
        self.assertEqual(
            runtime["runtime/int_cert_proof_identity.json"][0],
            "../../release/evidence/int_cert_proof_identity_v172.json",
        )

    def test_hermes_has_epoch_aware_archival_replay_dispatch(self) -> None:
        self.assertIn('"archival_range_checker"', self.source)
        self.assertNotIn('"archival_int_cert_checker"', self.source)
        self.assertIn('"archival_range_proof_identity"', self.source)
        # The historical int proof record remains packaged solely as
        # revocation evidence; no checker or replay dispatch is admitted.
        self.assertIn('"archival_int_cert_proof_identity"', self.source)
        verify_body = self.source.split("def tool_verify_receipt", 1)[1].split(
            "# -- pure-Q fragment adapters", 1
        )[0]
        self.assertIn("RANGE_ARCHIVAL_RELEASE_EPOCHS", verify_body)
        self.assertIn('_archival_checker("range")', verify_body)
        self.assertNotIn('_archival_checker("int-cert")', verify_body)
        self.assertIn("unsupported int-cert epoch", verify_body)

    def test_current_formal_tools_emit_the_v172_epoch(self) -> None:
        self.assertEqual(self.catalog["version"], "v1.7.3")
        range_body = self.source.split("def tool_range_bound", 1)[1].split(
            "def tool_gaussian_integral", 1
        )[0]
        int_body = self.source.split("def tool_integrate_bound_cert", 1)[1].split(
            "_VARIANT_PRODUCER_LABELS", 1
        )[0]
        rational_body = self.source.split("def _rational_bound_result", 1)[1].split(
            "def tool_sqrt_rat_bound", 1
        )[0]
        for body in (range_body, int_body, rational_body):
            self.assertIn("CURRENT_PROOF_RELEASE_EPOCH", body)
            self.assertNotIn('release_epoch="v1.5.0"', body)
            self.assertNotIn('release_epoch="v1.7.0"', body)

        rational_names = {
            "jackal_sqrt_rat_bound",
            "jackal_exp_rat_bound",
            "jackal_ln_rat_bound",
            "jackal_sin_rat_bound",
            "jackal_cos_rat_bound",
            "jackal_atan_rat_bound",
            "jackal_tanh_rat_bound",
        }
        for tool in self.catalog["tools"]:
            if tool["name"] in rational_names:
                self.assertEqual(tool["returns"]["release_epoch"], "v1.7.2")

    def test_current_plugin_smoke_requires_v172_receipts(self) -> None:
        source = PLUGIN_SMOKE.read_text(encoding="utf-8")
        self.assertIn('RANGE_CONTEXT = {\n    "expected_release_epoch": "v1.7.2"', source)
        self.assertIn('INT_CERT_CONTEXT = {\n    "expected_release_epoch": "v1.7.2"', source)
        self.assertIn('receipt.get("release_epoch") == "v1.7.2"', source)
        # Range, composed-integral, and three explicit rational round trips.
        # Gaussian deliberately remains on its unchanged v1.5 identity.
        self.assertEqual(source.count('"expected_release_epoch": "v1.7.2"'), 5)

    def test_plugin_smoke_cannot_pass_with_unexecuted_rows(self) -> None:
        source = PLUGIN_SMOKE.read_text(encoding="utf-8")
        self.assertIn(
            "all(row.get(\"ok\") is True for row in ROWS)",
            source,
        )
        self.assertNotIn(
            "record(sid, True, f\"SKIPPED-manifest-pending",
            source,
        )
        self.assertNotIn(
            'record("S1-bundle-hash-pin-matches", True,',
            source,
        )

    def test_current_mutation_battery_uses_v172_proof_context(self) -> None:
        source = CERT_MUTATIONS.read_text(encoding="utf-8")
        self.assertIn("range_proof_identity_v172.json", source)
        self.assertIn("CURRENT_PROOF_RELEASE_EPOCH", source)
        self.assertNotIn('release_epoch="v1.3.0"', source)
        self.assertNotIn('"--expected-release-epoch", "v1.3.0"', source)

    def test_claim_router_splits_current_rational_from_archival_gaussian(self) -> None:
        source = CLAIM_ROUTER.read_text(encoding="utf-8")
        self.assertIn("range_proof_identity_v172.json", source)
        self.assertIn("RATIONAL_RECEIPT_EPOCH = fr.CURRENT_PROOF_RELEASE_EPOCH", source)
        self.assertIn('GAUSSIAN_RECEIPT_EPOCH = "v1.5.0"', source)
        self.assertNotIn("RELEASE_EPOCH_RECEIPTS", source)
        wrapper = CLAIM_VERIFY_WRAPPER.read_text(encoding="utf-8")
        self.assertIn("range_proof_identity_v172.json", wrapper)


if __name__ == "__main__":
    unittest.main(verbosity=2)
