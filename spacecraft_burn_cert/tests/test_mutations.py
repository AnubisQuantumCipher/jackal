from __future__ import annotations

import importlib.util
import json
import os
import sys
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


def campaign_fixture(
    harness,
    root: Path,
    source_digest: str | None = None,
):
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        name: root / name
        for name in ("receipt", "request", "witness", "checker", "identity")
    }
    for name, path in paths.items():
        if name != "receipt":
            path.write_bytes(f"{name}-A".encode("ascii"))
    if source_digest is None:
        source_digest = harness.sha256(harness.SOURCE.read_bytes())
    paths["receipt"].write_text(json.dumps({"source_sha256": source_digest}))
    inputs = harness.FormalInputs(
        paths["receipt"],
        paths["request"],
        paths["witness"],
        paths["checker"],
        paths["identity"],
        harness.sha256(paths["receipt"].read_bytes()),
        harness.sha256(paths["identity"].read_bytes()),
        "c" * 64,
        harness.sha256(paths["request"].read_bytes()),
        "model",
        "epoch",
        "nonce",
    )
    binding = {
        "witness_sha256": harness.sha256(paths["witness"].read_bytes()),
        "checker_sha256": harness.sha256(paths["checker"].read_bytes()),
    }
    return inputs, binding, {"status": "ACCEPT", "binding": binding}, {
        "contract_valid": True
    }


def passing_witness_record(harness, name: str, binding: dict) -> dict:
    return {
        "mutation": name,
        "original_sha256": binding["witness_sha256"],
        "checker_sha256": binding["checker_sha256"],
        "checker_output_excerpt": harness.WITNESS_MUTATION_REFUSALS[name],
        "checker_returncode": 1,
        "checker_timed_out": False,
        "checker_output_limited": False,
        "outer_verifier": {
            "status": "REFUSED",
            "reasons": ["witness-hash-mismatch"],
        },
        "outer_verifier_returncode": 2,
        "outer_verifier_timed_out": False,
        "outer_verifier_output_limited": False,
        "caught": True,
    }


def passing_source_record(harness, name: str, digest: str, output_digest: str) -> dict:
    mutation = harness.MUTATIONS[name]
    return {
        "mutation": name,
        "bug": mutation["bug"],
        "expected_reason": mutation["expected_reason"],
        "a_before_sha256": digest,
        "b_sha256": harness.sha256(f"{name}-B".encode("ascii")),
        "a_after_sha256": digest,
        "restored": True,
        "restored_contract_test_passed": True,
        "restored_contract_test_output_limited": False,
        "mutant_tests_failed": True,
        "mutant_tests_timed_out": False,
        "mutant_tests_output_limited": False,
        "reason_observed": True,
        "mutant_test_output_sha256": output_digest,
        "detection_boundary": (
            "source contract tests; formal publication requires separately "
            "pinned immutable bytes"
        ),
        "caught": True,
    }


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
        record = harness.run(
            (
                sys.executable,
                "-I",
                "-c",
                "import os,time; os.write(1,b'partial output\\n'); time.sleep(10)",
            ),
            timeout=1,
        )
        self.assertEqual(record["returncode"], 124)
        self.assertEqual(record["output"], "partial output\n")
        self.assertEqual(record["output_excerpt"], record["output"])
        self.assertEqual(len(record["output_sha256"]), 64)
        self.assertFalse(record["output_limited"])

    def test_subprocess_output_is_killed_at_the_hard_capture_limit(self):
        harness = load_harness(self)
        record = harness.run(
            (
                sys.executable,
                "-I",
                "-c",
                "import os; os.write(1,b'x' * "
                f"{harness.MAX_SUBPROCESS_OUTPUT_CHARS + 4096})",
            ),
            timeout=10,
        )
        self.assertEqual(record["returncode"], 125)
        self.assertTrue(record["output_limited"])
        self.assertEqual(
            len(record["output"].encode("utf-8")),
            harness.MAX_SUBPROCESS_OUTPUT_CHARS,
        )

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

    def test_exercise_mutation_uses_only_parameterized_source_closure(self):
        harness = load_harness(self)
        source_a = harness.SOURCE.read_bytes()
        codec_a = harness.SOURCE.with_name("witness_codec.py").read_bytes()
        test_a = (harness.ROOT / "tests/test_certifier.py").read_bytes()
        baseline_a = (
            harness.ROOT / "evidence/legacy-v1/baseline_receipt.json"
        ).read_bytes()
        name = "meters_as_kilometers"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_repository = root / "snapshot"
            snapshot_cert = snapshot_repository / "spacecraft_burn_cert"
            closure_paths = {
                "source": snapshot_cert / "certify.py",
                "codec": snapshot_cert / "witness_codec.py",
                "test": snapshot_cert / "tests/test_certifier.py",
                "baseline": (
                    snapshot_cert
                    / "evidence/legacy-v1/baseline_receipt.json"
                ),
            }
            for field, data in (
                ("source", source_a),
                ("codec", codec_a),
                ("test", test_a),
                ("baseline", baseline_a),
            ):
                closure_paths[field].parent.mkdir(parents=True, exist_ok=True)
                closure_paths[field].write_bytes(data)
            closure = harness.SourceMutationInputs(
                repository_root=snapshot_repository,
                source=closure_paths["source"],
                codec=closure_paths["codec"],
                test=closure_paths["test"],
                baseline=closure_paths["baseline"],
            )

            live_repository = root / "live"
            live_cert = live_repository / "spacecraft_burn_cert"
            live_source = live_cert / "certify.py"
            live_codec = live_cert / "witness_codec.py"
            live_test = live_cert / "tests/test_certifier.py"
            live_baseline = (
                live_cert / "evidence/legacy-v1/baseline_receipt.json"
            )
            for path, data in (
                (live_source, source_a + b"\n# poisoned live source B\n"),
                (live_codec, b"poisoned live codec B\n"),
                (live_test, b"poisoned live test B\n"),
                (live_baseline, b"poisoned live baseline B\n"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

            commands = []

            def fake_run(command, timeout=150, extra_env=None):
                del timeout, extra_env
                commands.append(command)
                output = (
                    harness.MUTATIONS[name]["expected_reason"] + "\n"
                    if len(commands) == 1
                    else ""
                )
                return {
                    "returncode": 1 if len(commands) == 1 else 0,
                    "output": output,
                    "output_sha256": harness.sha256(output.encode("utf-8")),
                    "output_excerpt": output,
                    "output_limited": False,
                }

            with (
                mock.patch.object(harness, "ROOT", live_cert),
                mock.patch.object(harness, "SOURCE", live_source),
                mock.patch.object(harness, "BASELINE", live_baseline),
                mock.patch.object(harness, "run", side_effect=fake_run),
            ):
                record = harness.exercise_mutation(name, closure)
            closure_codec_after = closure.codec.read_bytes()
            closure_baseline_after = closure.baseline.read_bytes()

        expected_source_digest = harness.sha256(source_a)
        self.assertEqual(record["a_before_sha256"], expected_source_digest)
        self.assertEqual(record["a_after_sha256"], expected_source_digest)
        self.assertTrue(record["caught"])
        self.assertTrue(record["restored"])
        self.assertEqual(len(commands), 2)
        for command in commands:
            self.assertEqual(command[5], str(closure.test))
            self.assertEqual(command[6], str(closure.repository_root))
        self.assertEqual(closure_codec_after, codec_a)
        self.assertEqual(closure_baseline_after, baseline_a)

    def test_source_closure_snapshots_real_legacy_baseline_fixture(self):
        harness = load_harness(self)
        expected = (
            harness.ROOT
            / "evidence/legacy-v1/baseline_receipt.json"
        )
        self.assertTrue(expected.is_file())
        with tempfile.TemporaryDirectory() as directory:
            closure = harness.snapshot_source_mutation_inputs(
                Path(directory) / "repository"
            )
            observed = closure.baseline.read_bytes()
        self.assertEqual(harness.BASELINE, expected)
        self.assertEqual(observed, expected.read_bytes())

    def test_campaign_refuses_source_snapshot_not_bound_to_formal_receipt(self):
        harness = load_harness(self)
        source_a = b"\n".join(
            mutation["old"].encode("utf-8")
            for mutation in harness.MUTATIONS.values()
        )
        source_b = source_a + b"\n# receipt-bound live source B\n"
        codec_a = b"codec A\n"
        test_a = b"test A\n"
        baseline_a = b"legacy baseline A\n"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live_repository = root / "live"
            cert_root = live_repository / "spacecraft_burn_cert"
            source = cert_root / "certify.py"
            codec = cert_root / "witness_codec.py"
            test = cert_root / "tests/test_certifier.py"
            baseline = (
                cert_root / "evidence/legacy-v1/baseline_receipt.json"
            )
            for path, data in (
                (source, source_a),
                (codec, codec_a),
                (test, test_a),
                (baseline, baseline_a),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

            receipt_source_digest = harness.sha256(source_b)
            inputs, binding, accepted, process = campaign_fixture(
                harness,
                root / "formal-inputs",
                source_digest=receipt_source_digest,
            )
            baseline_calls = 0
            source_calls = 0

            def install_source(data, label):
                replacement = source.with_name(f".{source.name}.{label}")
                replacement.write_bytes(data)
                os.replace(replacement, source)

            def verify_baseline(_inputs):
                nonlocal baseline_calls
                baseline_calls += 1
                if baseline_calls == 1:
                    install_source(source_b, "B")
                else:
                    self.assertEqual(
                        harness.sha256(source.read_bytes()),
                        receipt_source_digest,
                    )
                return accepted, process

            def source_mutation(name, closure):
                nonlocal source_calls
                source_calls += 1
                digest = harness.sha256(closure.source.read_bytes())
                return passing_source_record(harness, name, digest, "e" * 64)

            refused = False
            try:
                with (
                    mock.patch.object(harness, "ROOT", cert_root),
                    mock.patch.object(harness, "SOURCE", source),
                    mock.patch.object(harness, "BASELINE", baseline),
                    mock.patch.object(
                        harness,
                        "verify_baseline",
                        side_effect=verify_baseline,
                    ),
                    mock.patch.object(
                        harness,
                        "exercise_mutation",
                        side_effect=source_mutation,
                    ),
                    mock.patch.object(
                        harness,
                        "exercise_witness_mutation",
                        side_effect=lambda name, _inputs: passing_witness_record(
                            harness, name, binding
                        ),
                    ),
                ):
                    result = harness.campaign(inputs)
            except RuntimeError:
                refused = True
            else:
                refused = result["status"] == "FAIL"
            finally:
                install_source(source_a, "A")

            self.assertTrue(refused)
            self.assertEqual(source_calls, 0)

    def test_campaign_snapshots_repository_shaped_source_mutation_closure(self):
        harness = load_harness(self)
        source_paths = {
            "source": harness.SOURCE,
            "codec": harness.SOURCE.with_name("witness_codec.py"),
            "test": harness.ROOT / "tests" / "test_certifier.py",
            "baseline": harness.ROOT / "evidence/legacy-v1/baseline_receipt.json",
        }
        source_bytes = {
            name: path.read_bytes() for name, path in source_paths.items()
        }
        source_digest = harness.sha256(source_bytes["source"])
        output_digest = harness.sha256(
            source_bytes["codec"]
            + source_bytes["test"]
            + source_bytes["baseline"]
        )
        observed = []

        with tempfile.TemporaryDirectory() as directory:
            inputs, binding, accepted, process = campaign_fixture(
                harness, Path(directory)
            )

            def source_mutation(name, closure):
                paths = {
                    "source": closure.source,
                    "codec": closure.codec,
                    "test": closure.test,
                    "baseline": closure.baseline,
                }
                command = harness.certifier_test_command(closure)
                observed.append(
                    {
                        "closure": closure,
                        "paths": paths,
                        "bytes": {
                            field: path.read_bytes()
                            for field, path in paths.items()
                        },
                        "command": command,
                    }
                )
                return passing_source_record(
                    harness,
                    name,
                    harness.sha256(paths["source"].read_bytes()),
                    harness.sha256(
                        paths["codec"].read_bytes()
                        + paths["test"].read_bytes()
                        + paths["baseline"].read_bytes()
                    ),
                )

            with (
                mock.patch.object(
                    harness,
                    "verify_baseline",
                    return_value=(accepted, process),
                ),
                mock.patch.object(
                    harness,
                    "exercise_mutation",
                    side_effect=source_mutation,
                ),
                mock.patch.object(
                    harness,
                    "exercise_witness_mutation",
                    side_effect=lambda name, _inputs: passing_witness_record(
                        harness, name, binding
                    ),
                ),
            ):
                result = harness.campaign(inputs)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(observed), len(harness.MUTATIONS))
        closure = observed[0]["closure"]
        expected_relative_paths = {
            "source": Path("spacecraft_burn_cert/certify.py"),
            "codec": Path("spacecraft_burn_cert/witness_codec.py"),
            "test": Path("spacecraft_burn_cert/tests/test_certifier.py"),
            "baseline": Path(
                "spacecraft_burn_cert/evidence/legacy-v1/baseline_receipt.json"
            ),
        }
        for item in observed:
            self.assertIs(item["closure"], closure)
            self.assertEqual(item["bytes"], source_bytes)
            for field, expected_relative in expected_relative_paths.items():
                path = item["paths"][field]
                self.assertEqual(
                    path.relative_to(closure.repository_root),
                    expected_relative,
                )
                self.assertNotEqual(path, source_paths[field])
            self.assertEqual(
                item["command"][5],
                str(closure.test),
            )
            self.assertEqual(
                item["command"][6],
                str(closure.repository_root),
            )
        self.assertEqual(
            {row["a_before_sha256"] for row in result["mutations"]},
            {source_digest},
        )
        self.assertEqual(
            {row["a_after_sha256"] for row in result["mutations"]},
            {source_digest},
        )
        self.assertEqual(
            {row["mutant_test_output_sha256"] for row in result["mutations"]},
            {output_digest},
        )

    def test_source_mutation_closure_aba_cannot_change_pass_evidence(self):
        harness = load_harness(self)
        source_a = b"\n".join(
            mutation["old"].encode("utf-8")
            for mutation in harness.MUTATIONS.values()
        )
        source_b = source_a + b"\n# swapped source B\n"
        codec_a = b"codec A\n"
        codec_b = b"codec B\n"
        test_a = b"test A\n"
        test_b = b"test B\n"
        baseline_a = b"baseline A\n"
        baseline_b = b"baseline B\n"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live_repository = root / "live"
            cert_root = live_repository / "spacecraft_burn_cert"
            source = cert_root / "certify.py"
            codec = cert_root / "witness_codec.py"
            test = cert_root / "tests/test_certifier.py"
            baseline = cert_root / "evidence/legacy-v1/baseline_receipt.json"
            for path, data in (
                (source, source_a),
                (codec, codec_a),
                (test, test_a),
                (baseline, baseline_a),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            inputs, binding, accepted, process = campaign_fixture(
                harness,
                root / "formal",
                source_digest=harness.sha256(source_a),
            )
            baseline_calls = 0

            def replace_path(path, data, label):
                replacement = path.with_name(f".{path.name}.{label}")
                replacement.write_bytes(data)
                os.replace(replacement, path)

            def verify_baseline(_inputs):
                nonlocal baseline_calls
                baseline_calls += 1
                if baseline_calls == 1:
                    replace_path(source, source_b, "B")
                    replace_path(codec, codec_b, "B")
                    replace_path(test, test_b, "B")
                    replace_path(baseline, baseline_b, "B")
                return accepted, process

            def source_mutation(name, *closure_argument):
                if closure_argument:
                    closure = closure_argument[0]
                    source_path = closure.source
                    codec_path = closure.codec
                    test_path = closure.test
                    baseline_path = closure.baseline
                else:
                    source_path = source
                    codec_path = codec
                    test_path = test
                    baseline_path = baseline
                record = passing_source_record(
                    harness,
                    name,
                    harness.sha256(source_path.read_bytes()),
                    harness.sha256(
                        codec_path.read_bytes()
                        + test_path.read_bytes()
                        + baseline_path.read_bytes()
                    ),
                )
                if name == tuple(harness.MUTATIONS)[-1]:
                    replace_path(source, source_a, "A")
                    replace_path(codec, codec_a, "A")
                    replace_path(test, test_a, "A")
                    replace_path(baseline, baseline_a, "A")
                return record

            with (
                mock.patch.object(harness, "ROOT", cert_root),
                mock.patch.object(harness, "SOURCE", source),
                mock.patch.object(harness, "BASELINE", baseline),
                mock.patch.object(
                    harness,
                    "verify_baseline",
                    side_effect=verify_baseline,
                ),
                mock.patch.object(
                    harness,
                    "exercise_mutation",
                    side_effect=source_mutation,
                ),
                mock.patch.object(
                    harness,
                    "exercise_witness_mutation",
                    side_effect=lambda name, _inputs: passing_witness_record(
                        harness, name, binding
                    ),
                ),
            ):
                result = harness.campaign(inputs)

            expected_source_digest = harness.sha256(source_a)
            expected_output_digest = harness.sha256(
                codec_a + test_a + baseline_a
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(baseline_calls, 2)
            self.assertEqual(source.read_bytes(), source_a)
            self.assertEqual(codec.read_bytes(), codec_a)
            self.assertEqual(test.read_bytes(), test_a)
            self.assertEqual(baseline.read_bytes(), baseline_a)
            for record in result["mutations"]:
                self.assertEqual(
                    record["a_before_sha256"],
                    expected_source_digest,
                )
                self.assertEqual(
                    record["a_after_sha256"],
                    expected_source_digest,
                )
                self.assertEqual(
                    record["mutant_test_output_sha256"],
                    expected_output_digest,
                )

    def test_campaign_pass_rechecks_each_source_record_against_baseline_digest(self):
        harness = load_harness(self)
        source_digest = harness.sha256(harness.SOURCE.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            inputs, binding, accepted, process = campaign_fixture(
                harness, Path(directory)
            )
            for field in ("a_before_sha256", "a_after_sha256"):
                with self.subTest(field=field):
                    def source_mutation(name, *_closure):
                        record = passing_source_record(
                            harness,
                            name,
                            source_digest,
                            "e" * 64,
                        )
                        if name == "center_only":
                            record[field] = "0" * 64
                        return record

                    with (
                        mock.patch.object(
                            harness,
                            "verify_baseline",
                            return_value=(accepted, process),
                        ),
                        mock.patch.object(
                            harness,
                            "exercise_mutation",
                            side_effect=source_mutation,
                        ),
                        mock.patch.object(
                            harness,
                            "exercise_witness_mutation",
                            side_effect=lambda name, _inputs: (
                                passing_witness_record(harness, name, binding)
                            ),
                        ),
                    ):
                        result = harness.campaign(inputs)
                    self.assertEqual(result["status"], "FAIL")

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
            timed_out["output_limited"] = False
            refused["output_limited"] = False
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
        self.assertTrue(harness.witness_mutation_caught(1, 2, refused))
        self.assertFalse(harness.witness_mutation_caught(124, 2, refused))
        self.assertFalse(harness.witness_mutation_caught(1, 0, refused))
        self.assertFalse(harness.witness_mutation_caught(1, 124, refused))
        self.assertFalse(harness.witness_mutation_caught(2, 2, refused))
        self.assertFalse(
            harness.witness_mutation_caught(
                1, 2, {"status": "ACCEPT", "reasons": []}
            )
        )
        self.assertTrue(harness.mutant_failure_caught(1, "unit-scale-mismatch", "unit-scale-mismatch"))
        self.assertFalse(harness.mutant_failure_caught(1, "generic failure", "unit-scale-mismatch"))

    def test_json_parser_uses_complete_output_not_reporting_excerpt(self):
        harness = load_harness(self)
        record = {"output": '{"status":"ACCEPT"}', "output_excerpt": 'CEPT"}'}
        self.assertEqual(harness.parse_json_output(record), {"status": "ACCEPT"})

    def test_json_parser_refuses_every_unbounded_or_ambiguous_shape(self):
        harness = load_harness(self)
        malformed = (
            "[" * 5000 + "0" + "]" * 5000,
            '{"x":0,"x":1}',
            '{"x":NaN}',
            '{"x":1.5}',
            '{"x":"\\ud800"}',
            '{"x":' + "9" * (harness.MAX_JSON_INTEGER_DIGITS + 1) + "}",
            "[]",
        )
        for output in malformed:
            with self.subTest(output=output[:40]):
                self.assertIsNone(harness.parse_json_output({"output": output}))
        self.assertIsNone(harness.parse_json_output({}))
        self.assertIsNone(
            harness.parse_json_output(
                {"output": "x" * (harness.MAX_SUBPROCESS_OUTPUT_CHARS + 1)}
            )
        )

    def test_baseline_acceptance_requires_the_exact_cli_exit_contract(self):
        harness = load_harness(self)
        accepted = {
            "returncode": 0,
            "output": '{"status":"ACCEPT","reasons":[]}',
            "output_sha256": "a" * 64,
            "output_excerpt": "",
            "output_limited": False,
        }
        inputs = mock.Mock()
        with mock.patch.object(harness, "run", return_value=accepted):
            result, process = harness.verify_baseline(inputs)
        self.assertEqual(result["status"], "ACCEPT")
        self.assertTrue(process["contract_valid"])

        for returncode in (1, 2, 124):
            with self.subTest(returncode=returncode):
                record = {**accepted, "returncode": returncode}
                with mock.patch.object(harness, "run", return_value=record):
                    _result, process = harness.verify_baseline(inputs)
                self.assertFalse(process["contract_valid"])

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

    def test_campaign_uses_one_private_formal_input_snapshot_for_every_formal_step(self):
        harness = load_harness(self)
        refusal_lines = {
            "corruption": "REJECT noncanonical-control-character\n",
            "chain": "REJECT picard-strict-interior\n",
            "coverage": "REJECT cutoff-coverage\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                name: root / name
                for name in ("receipt", "request", "witness", "checker", "identity")
            }
            original_bytes = {
                "receipt": json.dumps({
                    "source_sha256": harness.sha256(harness.SOURCE.read_bytes())
                }).encode("utf-8"),
                "request": b"request-A",
                "witness": b"witness-A",
                "checker": b"checker-A",
                "identity": b"identity-A",
                "verifier": harness.VERIFIER.read_bytes(),
            }
            for name, path in paths.items():
                path.write_bytes(original_bytes[name])
            inputs = harness.FormalInputs(
                paths["receipt"],
                paths["request"],
                paths["witness"],
                paths["checker"],
                paths["identity"],
                "a" * 64,
                "b" * 64,
                "c" * 64,
                "d" * 64,
                "model",
                "epoch",
                "nonce",
            )
            binding = {
                "witness_sha256": harness.sha256(original_bytes["witness"]),
                "checker_sha256": harness.sha256(original_bytes["checker"]),
            }
            accepted = {"status": "ACCEPT", "binding": binding}
            process = {"contract_valid": True}
            observed = []

            def capture(current):
                names = (
                    "receipt",
                    "request",
                    "witness",
                    "checker",
                    "proof_identity",
                    "verifier",
                )
                observed.append(
                    (
                        current,
                        tuple(getattr(current, name).read_bytes() for name in names),
                    )
                )

            def baseline(current):
                capture(current)
                return accepted, process

            def witness_mutation(name, current):
                capture(current)
                return {
                    "mutation": name,
                    "original_sha256": binding["witness_sha256"],
                    "checker_sha256": binding["checker_sha256"],
                    "checker_output_excerpt": refusal_lines[name],
                    "checker_returncode": 1,
                    "checker_timed_out": False,
                    "checker_output_limited": False,
                    "outer_verifier": {
                        "status": "REFUSED",
                        "reasons": ["witness-hash-mismatch"],
                    },
                    "outer_verifier_returncode": 2,
                    "outer_verifier_timed_out": False,
                    "outer_verifier_output_limited": False,
                    "caught": True,
                }

            source_record = {
                "a_before_sha256": harness.sha256(harness.SOURCE.read_bytes()),
                "a_after_sha256": harness.sha256(harness.SOURCE.read_bytes()),
                "caught": True,
                "restored": True,
                "restored_contract_test_passed": True,
            }
            with (
                mock.patch.object(harness, "verify_baseline", side_effect=baseline),
                mock.patch.object(
                    harness, "exercise_mutation", return_value=source_record
                ),
                mock.patch.object(
                    harness,
                    "exercise_witness_mutation",
                    side_effect=witness_mutation,
                ),
            ):
                result = harness.campaign(inputs)

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(len(observed), 5)
            snapshot = observed[0][0]
            expected_snapshots = tuple(
                original_bytes[name]
                for name in (
                    "receipt",
                    "request",
                    "witness",
                    "checker",
                    "identity",
                    "verifier",
                )
            )
            for current, snapshots in observed:
                self.assertEqual(current, snapshot)
                self.assertEqual(snapshots, expected_snapshots)
            for name in (
                "receipt",
                "request",
                "witness",
                "checker",
                "proof_identity",
                "verifier",
            ):
                self.assertNotEqual(getattr(snapshot, name), getattr(inputs, name))

    def test_witness_mutations_bind_exact_checker_refusals_and_formal_digests(self):
        harness = load_harness(self)
        interval = witness_codec.Interval(0, 10)
        box = witness_codec.Box((interval,) * 5)
        witness = witness_codec.BurnWitness(
            80,
            1,
            32,
            (1, 1, 1, 1, 1, 1),
            2,
            1,
            (
                witness_codec.BranchWitness(
                    0,
                    box,
                    interval,
                    (
                        witness_codec.StepWitness(0, 0, box),
                        witness_codec.StepWitness(0, 1, box),
                    ),
                ),
            ),
        )
        original = witness_codec.encode_witness(witness)
        refusal_lines = {
            "corruption": "REJECT noncanonical-control-character\n",
            "chain": "REJECT picard-strict-interior\n",
            "coverage": "REJECT cutoff-coverage\n",
        }

        def process(returncode, output):
            return {
                "returncode": returncode,
                "output": output,
                "output_sha256": harness.sha256(output.encode("utf-8")),
                "output_excerpt": output,
                "output_limited": False,
            }

        outer_refusal = process(
            2,
            '{"status":"REFUSED","reasons":["witness-hash-mismatch"]}',
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            witness_path = root / "witness.cert"
            checker_path = root / "checker"
            witness_path.write_bytes(original)
            checker_bytes = b"accepted baseline checker bytes"
            checker_path.write_bytes(checker_bytes)
            inputs = harness.FormalInputs(
                root / "receipt.json",
                root / "request.json",
                witness_path,
                checker_path,
                root / "identity.json",
                "a" * 64,
                "b" * 64,
                "c" * 64,
                "d" * 64,
                "model",
                "epoch",
                "nonce",
            )
            accepted_binding = {
                "witness_sha256": harness.sha256(original),
                "checker_sha256": harness.sha256(checker_bytes),
            }
            for name, refusal_line in refusal_lines.items():
                with self.subTest(name=name, refusal="exact"):
                    with mock.patch.object(
                        harness,
                        "run",
                        side_effect=(process(1, refusal_line), outer_refusal),
                    ):
                        record = harness.exercise_witness_mutation(name, inputs)
                    self.assertEqual(
                        record["original_sha256"],
                        accepted_binding["witness_sha256"],
                    )
                    self.assertEqual(
                        record.get("checker_sha256"),
                        accepted_binding["checker_sha256"],
                    )
                    self.assertEqual(record["checker_output_excerpt"], refusal_line)
                    self.assertTrue(record["caught"])

                with self.subTest(name=name, refusal="wrong"):
                    with mock.patch.object(
                        harness,
                        "run",
                        side_effect=(
                            process(1, "REJECT unrelated-refusal\n"),
                            outer_refusal,
                        ),
                    ):
                        record = harness.exercise_witness_mutation(name, inputs)
                    self.assertFalse(record["caught"])

    def test_verifier_path_aba_cannot_change_campaign_commands(self):
        harness = load_harness(self)
        interval = witness_codec.Interval(0, 10)
        box = witness_codec.Box((interval,) * 5)
        witness = witness_codec.BurnWitness(
            80,
            1,
            32,
            (1, 1, 1, 1, 1, 1),
            2,
            1,
            (
                witness_codec.BranchWitness(
                    0,
                    box,
                    interval,
                    (
                        witness_codec.StepWitness(0, 0, box),
                        witness_codec.StepWitness(0, 1, box),
                    ),
                ),
            ),
        )
        witness_bytes = witness_codec.encode_witness(witness)
        verifier_a = b"verifier A\n"
        verifier_b = b"malicious verifier B\n"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs, _binding, _accepted, process = campaign_fixture(
                harness, root / "formal"
            )
            inputs.witness.write_bytes(witness_bytes)
            checker_bytes = inputs.checker.read_bytes()
            binding = {
                "witness_sha256": harness.sha256(witness_bytes),
                "checker_sha256": harness.sha256(checker_bytes),
            }
            accepted = {"status": "ACCEPT", "binding": binding}
            live_verifier = root / "verify_receipt.py"
            live_verifier.write_bytes(verifier_a)
            inputs = harness.FormalInputs(
                inputs.receipt,
                inputs.request,
                inputs.witness,
                inputs.checker,
                inputs.proof_identity,
                inputs.receipt_sha256,
                inputs.proof_file_sha256,
                inputs.proof_identity_sha256,
                inputs.request_digest,
                inputs.model_id,
                inputs.epoch,
                inputs.nonce,
                verifier=live_verifier,
            )
            verifier_commands = []

            def replace_verifier(data, label):
                replacement = live_verifier.with_name(
                    f".{live_verifier.name}.{label}"
                )
                replacement.write_bytes(data)
                os.replace(replacement, live_verifier)

            def record(returncode, output):
                return {
                    "returncode": returncode,
                    "output": output,
                    "output_sha256": harness.sha256(output.encode("utf-8")),
                    "output_excerpt": output,
                    "output_limited": False,
                }

            def fake_run(command, timeout=150, extra_env=None):
                del timeout, extra_env
                if command[0] != str(harness.PYTHON):
                    name = Path(command[1]).stem
                    return record(
                        1,
                        harness.WITNESS_MUTATION_REFUSALS[name],
                    )
                verifier_path = Path(command[3])
                verifier_commands.append(
                    (verifier_path, verifier_path.read_bytes())
                )
                call = len(verifier_commands)
                if call == 1:
                    replace_verifier(verifier_b, "B")
                if call == 4:
                    replace_verifier(verifier_a, "A")
                if call in {1, 5}:
                    return record(0, json.dumps(accepted))
                return record(
                    2,
                    json.dumps({
                        "status": "REFUSED",
                        "reasons": ["witness-hash-mismatch"],
                    }),
                )

            source_digest = harness.sha256(harness.SOURCE.read_bytes())
            source_record = {
                "a_before_sha256": source_digest,
                "a_after_sha256": source_digest,
                "caught": True,
                "restored": True,
                "restored_contract_test_passed": True,
            }
            with (
                mock.patch.object(harness, "VERIFIER", live_verifier),
                mock.patch.object(harness, "run", side_effect=fake_run),
                mock.patch.object(
                    harness,
                    "exercise_mutation",
                    return_value=source_record,
                ),
            ):
                result = harness.campaign(inputs)

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(len(verifier_commands), 5)
            snapshot_path = verifier_commands[0][0]
            self.assertNotEqual(snapshot_path, live_verifier)
            for path, observed_bytes in verifier_commands:
                self.assertEqual(path, snapshot_path)
                self.assertEqual(observed_bytes, verifier_a)
            self.assertEqual(live_verifier.read_bytes(), verifier_a)

    def test_campaign_aba_replacement_cannot_change_snapshotted_formal_inputs(self):
        harness = load_harness(self)
        interval = witness_codec.Interval(0, 10)
        box = witness_codec.Box((interval,) * 5)
        witness = witness_codec.BurnWitness(
            80,
            1,
            32,
            (1, 1, 1, 1, 1, 1),
            2,
            1,
            (
                witness_codec.BranchWitness(
                    0,
                    box,
                    interval,
                    (
                        witness_codec.StepWitness(0, 0, box),
                        witness_codec.StepWitness(0, 1, box),
                    ),
                ),
            ),
        )
        witness_a = witness_codec.encode_witness(witness)
        witness_b = harness.mutated_witness(witness_a, "coverage")
        checker_a = b"accepted checker A"
        checker_b = b"swapped checker B"
        refusal_lines = {
            "corruption": "REJECT noncanonical-control-character\n",
            "chain": "REJECT picard-strict-interior\n",
            "coverage": "REJECT cutoff-coverage\n",
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "receipt.json"
            request = root / "request.json"
            witness_path = root / "witness.cert"
            checker_path = root / "checker"
            identity = root / "identity.json"
            for path in (request, identity):
                path.write_bytes(path.name.encode("ascii"))
            receipt.write_text(json.dumps({
                "source_sha256": harness.sha256(harness.SOURCE.read_bytes())
            }))
            witness_path.write_bytes(witness_a)
            checker_path.write_bytes(checker_a)
            inputs = harness.FormalInputs(
                receipt,
                request,
                witness_path,
                checker_path,
                identity,
                "a" * 64,
                "b" * 64,
                "c" * 64,
                "d" * 64,
                "model",
                "epoch",
                "nonce",
            )
            binding = {
                "witness_sha256": harness.sha256(witness_a),
                "checker_sha256": harness.sha256(checker_a),
            }
            accepted = {"status": "ACCEPT", "binding": binding}
            process = {"contract_valid": True}
            baseline_calls = 0

            def replace_path(path, data, label):
                replacement = path.with_name(f".{path.name}.{label}")
                replacement.write_bytes(data)
                os.replace(replacement, path)

            def baseline(_current):
                nonlocal baseline_calls
                baseline_calls += 1
                if baseline_calls == 1:
                    replace_path(witness_path, witness_b, "B")
                    replace_path(checker_path, checker_b, "B")
                return accepted, process

            def witness_mutation(name, current):
                original_digest = harness.sha256(current.witness.read_bytes())
                checker_digest = harness.sha256(current.checker.read_bytes())
                record = {
                    "mutation": name,
                    "original_sha256": original_digest,
                    "checker_sha256": checker_digest,
                    "checker_output_excerpt": refusal_lines[name],
                    "checker_returncode": 1,
                    "checker_timed_out": False,
                    "checker_output_limited": False,
                    "outer_verifier": {
                        "status": "REFUSED",
                        "reasons": ["witness-hash-mismatch"],
                    },
                    "outer_verifier_returncode": 2,
                    "outer_verifier_timed_out": False,
                    "outer_verifier_output_limited": False,
                    "caught": True,
                }
                if name == "coverage":
                    replace_path(witness_path, witness_a, "A")
                    replace_path(checker_path, checker_a, "A")
                return record

            source_record = {
                "a_before_sha256": harness.sha256(harness.SOURCE.read_bytes()),
                "a_after_sha256": harness.sha256(harness.SOURCE.read_bytes()),
                "caught": True,
                "restored": True,
                "restored_contract_test_passed": True,
            }
            with (
                mock.patch.object(harness, "verify_baseline", side_effect=baseline),
                mock.patch.object(
                    harness, "exercise_mutation", return_value=source_record
                ),
                mock.patch.object(
                    harness,
                    "exercise_witness_mutation",
                    side_effect=witness_mutation,
                ),
            ):
                result = harness.campaign(inputs)

            self.assertEqual(baseline_calls, 2)
            self.assertEqual(witness_path.read_bytes(), witness_a)
            self.assertEqual(checker_path.read_bytes(), checker_a)
            self.assertEqual(result["status"], "PASS")
            for record in result["witness_mutations"]:
                self.assertEqual(
                    record["original_sha256"],
                    binding["witness_sha256"],
                )
                self.assertEqual(
                    record["checker_sha256"],
                    binding["checker_sha256"],
                )
                self.assertEqual(
                    record["checker_output_excerpt"],
                    refusal_lines[record["mutation"]],
                )

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
