from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from spacecraft_burn_cert import witness_codec


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
    def test_cli_refuses_symlink_hardlink_and_resolved_parent_output_aliases(self):
        harness = load_harness(self)
        for case in ("symlink", "dangling-symlink", "hardlink", "resolved-parent"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                real = root / "real"
                real.mkdir()
                baseline = real / "baseline.json"
                original = b"authoritative baseline\n"
                baseline.write_bytes(original)
                request = root / "request.json"
                witness = root / "witness.cert"
                checker = root / "checker"
                identity = root / "identity.json"
                for path in (request, witness, checker, identity):
                    path.write_bytes(path.name.encode("ascii"))
                if case == "symlink":
                    output = root / "output.json"
                    output.symlink_to(baseline)
                elif case == "dangling-symlink":
                    output = root / "output.json"
                    output.symlink_to(root / "missing.json")
                elif case == "hardlink":
                    output = root / "output.json"
                    os.link(baseline, output)
                else:
                    alias = root / "alias"
                    alias.symlink_to(real, target_is_directory=True)
                    output = alias / baseline.name
                argv = [
                    "--output", str(output), "--baseline", str(baseline),
                    "--request", str(request), "--witness", str(witness),
                    "--checker", str(checker), "--proof-identity", str(identity),
                    "--expected-receipt-sha256", "a" * 64,
                    "--expected-proof-file-sha256", "b" * 64,
                    "--expected-proof-identity-sha256", "c" * 64,
                    "--expected-request-digest", "d" * 64,
                    "--expected-model-id", "model", "--expected-epoch", "epoch",
                    "--nonce", "nonce",
                ]
                with mock.patch.object(
                    harness, "campaign", return_value={"status": "PASS"}
                ) as campaign:
                    with self.assertRaises(SystemExit):
                        harness.main(argv)
                campaign.assert_not_called()
                self.assertEqual(baseline.read_bytes(), original)

    def test_atomic_evidence_write_completes_short_writes(self):
        harness = load_harness(self)
        payload = {"status": "PASS", "detail": "x" * 4096}
        real_write = os.write

        def short_write(descriptor, data):
            return real_write(descriptor, data[:max(1, len(data) // 4)])

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.json"
            with mock.patch.object(harness.os, "write", side_effect=short_write) as write:
                harness.write_atomic(output, payload)
            self.assertGreater(write.call_count, 1)
            self.assertEqual(json.loads(output.read_bytes()), payload)

    def test_timeout_byte_output_is_preserved_as_text_evidence(self):
        harness = load_harness(self)
        timeout = subprocess.TimeoutExpired(
            ["probe"], 1, output=b"partial stdout\n", stderr=b"partial stderr\n"
        )
        with mock.patch.object(harness.subprocess, "run", side_effect=timeout):
            record = harness.run(("probe",), timeout=1)
        self.assertEqual(record["returncode"], 124)
        self.assertEqual(record["output"], "partial stdout\npartial stderr\n")
        self.assertEqual(record["output_excerpt"], record["output"])
        self.assertEqual(len(record["output_sha256"]), 64)

    def test_mutant_test_output_hash_ignores_temp_paths_and_elapsed_time(self):
        harness = load_harness(self)
        first = (
            "Traceback: /private/tmp/spacecraft-source-mutation-a1/certify.py\n"
            "Ran 9 tests in 0.123s\n"
        )
        second = (
            "Traceback: /private/tmp/spacecraft-source-mutation-b2/certify.py\n"
            "Ran 9 tests in 1.987s\n"
        )
        first_path = Path("/private/tmp/spacecraft-source-mutation-a1/certify.py")
        second_path = Path("/private/tmp/spacecraft-source-mutation-b2/certify.py")
        self.assertEqual(
            harness.normalized_mutant_test_output(first, first_path),
            harness.normalized_mutant_test_output(second, second_path),
        )

    def test_repeated_source_mutation_has_identical_output_evidence_hash(self):
        harness = load_harness(self)
        first = harness.exercise_mutation("meters_as_kilometers")
        second = harness.exercise_mutation("meters_as_kilometers")
        self.assertEqual(
            first["mutant_test_output_sha256"],
            second["mutant_test_output_sha256"],
        )

    def test_source_mutation_runner_ignores_hostile_python_environment(self):
        harness = load_harness(self)
        with tempfile.TemporaryDirectory() as directory:
            hostile = Path(directory)
            (hostile / "unittest.py").write_text(
                'raise RuntimeError("hostile PYTHONPATH imported")\n'
            )
            with mock.patch.dict(
                harness.os.environ,
                {
                    "PYTHONPATH": str(hostile),
                    "PYTHONWARNINGS": "error",
                    "PYTHONSTARTUP": str(hostile / "startup.py"),
                },
            ):
                result = harness.exercise_mutation("meters_as_kilometers")
        self.assertTrue(result["caught"])
        self.assertFalse(result["mutant_tests_timed_out"])

    def test_witness_timeout_cannot_pass_the_integrated_mutation_path(self):
        harness = load_harness(self)
        interval = witness_codec.Interval(0, 10)
        box = witness_codec.Box((interval,) * 5)
        witness = witness_codec.BurnWitness(
            80, 1, 32, (1, 1, 1, 1, 1, 1), 2, 1,
            (witness_codec.BranchWitness(0, box, interval, (
                witness_codec.StepWitness(0, 0, box),
                witness_codec.StepWitness(0, 1, box),
            )),),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            witness_path = root / "witness.cert"
            witness_path.write_bytes(witness_codec.encode_witness(witness))
            inputs = harness.FormalInputs(
                root / "receipt.json", root / "request.json", witness_path,
                root / "checker",
                root / "identity.json", "a" * 64, "b" * 64, "c" * 64,
                "d" * 64, "model", "epoch", "nonce",
            )
            timed_out = {"returncode": 124, "output": "", "output_sha256": "0", "output_excerpt": ""}
            refused = {
                "returncode": 2,
                "output": '{"status":"REFUSED","reasons":["witness-hash-mismatch"]}',
                "output_sha256": "1", "output_excerpt": "",
            }
            with mock.patch.object(harness, "run", side_effect=(timed_out, refused)):
                result = harness.exercise_witness_mutation("corruption", inputs)
            self.assertTrue(result["checker_timed_out"])
            self.assertFalse(result["checker_refused"])
            self.assertFalse(result["caught"])

    def test_timeout_is_not_counted_as_a_caught_mutation(self):
        harness = load_harness(self)
        self.assertTrue(harness.completed_mutant_failure(1))
        self.assertFalse(harness.completed_mutant_failure(0))
        self.assertFalse(harness.completed_mutant_failure(124))
        refused = {"status": "REFUSED", "reasons": ["witness-hash-mismatch"]}
        self.assertTrue(harness.witness_mutation_caught(1, refused))
        self.assertFalse(harness.witness_mutation_caught(124, refused))
        self.assertTrue(harness.mutant_failure_caught(1, "unit-scale-mismatch", "unit-scale-mismatch"))
        self.assertFalse(harness.mutant_failure_caught(1, "generic failure", "unit-scale-mismatch"))

    def test_json_parser_uses_complete_output_not_reporting_excerpt(self):
        harness = load_harness(self)
        record = {"output": '{"status":"ACCEPT"}', "output_excerpt": 'CEPT"}'}
        self.assertEqual(harness.parse_json_output(record), {"status": "ACCEPT"})

    def test_chain_coverage_and_corruption_mutations_change_exact_witness_bytes(self):
        harness = load_harness(self)
        interval = witness_codec.Interval(0, 10)
        box = witness_codec.Box((interval,) * 5)
        witness = witness_codec.BurnWitness(
            80, 1, 32, (1, 1, 1, 1, 1, 1), 2, 1,
            (witness_codec.BranchWitness(
                0, box, interval,
                (witness_codec.StepWitness(0, 0, box), witness_codec.StepWitness(0, 1, box)),
            ),),
        )
        encoded = witness_codec.encode_witness(witness)
        for name in ("chain", "coverage", "corruption"):
            with self.subTest(name=name):
                mutant = harness.mutated_witness(encoded, name)
                self.assertNotEqual(mutant, encoded)
        witness_codec.decode_witness(harness.mutated_witness(encoded, "chain"))
        witness_codec.decode_witness(harness.mutated_witness(encoded, "coverage"))
        with self.assertRaises(witness_codec.WitnessRefusal):
            witness_codec.decode_witness(harness.mutated_witness(encoded, "corruption"))

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
        with tempfile.TemporaryDirectory() as directory:
            isolated = Path(directory) / "certify.py"
            isolated.write_bytes((ROOT / "certify.py").read_bytes())
            result = harness.hash_only_cycle("round_margin_upward", isolated)
            self.assertNotEqual(result["a_before_sha256"], result["b_sha256"])
            self.assertEqual(result["a_before_sha256"], result["a_after_sha256"])
            self.assertTrue(result["restored"])

    def test_atomic_evidence_write_cleans_temporary_on_replace_failure(self):
        harness = load_harness(self)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.json"
            with mock.patch.object(harness.os, "replace", side_effect=OSError("blocked")):
                with self.assertRaisesRegex(OSError, "blocked"):
                    harness.write_atomic(output, {"status": "PASS"})
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
