#!/usr/bin/env python3
"""Hostile regressions for independently reviewed Navier--Stokes blockers."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ACCOUNT_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
ANUBIS_LOCATOR_ID = "macos-account-home-relative-v1:anubis-a733565f237d"
ANUBIS_RELATIVE_CANDIDATES = [
    "Library/Application Support/JACKAL/anubis-pins/anubis-a733565f237d",
    "anubis-lang/vm/pins/anubis-a733565f237d",
]
PINNED_ANUBIS = ACCOUNT_HOME / ANUBIS_RELATIVE_CANDIDATES[1]
MUTABLE_ANUBIS = ACCOUNT_HOME / "anubis-lang/target/release/anubis"
ANUBIS = PINNED_ANUBIS
ANUBIS_SHA256 = "a733565f237df171e7cf93b9b37700a42d8713576818fd92f8cd23a8ad7a69e2"
ANUBIS_SIZE = 99_415_712
HISTORICAL_FAILED_MUTABLE_SHA256 = (
    "666b021815c3591437433bcdf881d063a8da0c5b055a5f4f23bd7bee865befd9"
)
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import navier_stokes_certificate_producer as producer_module  # noqa: E402
import navier_stokes_receipt_verify as verifier_module  # noqa: E402
from navier_stokes_certificate_producer import (  # noqa: E402
    canonical_json_bytes,
    produce_receipt,
    protocol_lines,
    sha256_bytes,
)
from navier_stokes_gate_test import gate_a_request, gate_b_request, gate_s_request  # noqa: E402
from navier_stokes_receipt_verify import ReceiptRefusal, verify_receipt  # noqa: E402


def _repin_receipt(receipt: dict) -> None:
    body = {key: receipt[key] for key in receipt if key != "receipt_sha256"}
    receipt["receipt_sha256"] = sha256_bytes(canonical_json_bytes(body))


def _direct_anubis_result(request: dict) -> dict[str, str]:
    protocol = ("\n".join(protocol_lines(request)) + "\n").encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="navier-direct-kernel-") as temporary:
        temporary_path = Path(temporary)
        protocol_path = temporary_path / "request.protocol"
        output_path = temporary_path / "native"
        protocol_path.write_bytes(protocol)
        completed = subprocess.run(
            [str(ANUBIS), "run", "--out", str(output_path), str(ROOT / "domain_packs/pde/navier_stokes_v1.anb"), "--", str(protocol_path)],
            cwd=ROOT,
            env={
                "PATH": os.pathsep.join(
                    (
                        str(ACCOUNT_HOME / ".cargo/bin"),
                        "/usr/bin",
                        "/bin",
                        "/usr/sbin",
                        "/sbin",
                        "/opt/homebrew/bin",
                    )
                ),
                "CARGO_HOME": str(ACCOUNT_HOME / ".cargo"),
                "RUSTUP_HOME": str(ACCOUNT_HOME / ".rustup"),
                "TMPDIR": temporary,
                "LANG": "C",
                "LC_ALL": "C",
            },
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    if completed.returncode != 0:
        raise AssertionError(f"direct Anubis failed: {completed.stderr[-1000:]}")
    return dict(line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line)


class NavierStokesReleaseBlockerTests(unittest.TestCase):
    def test_plan_uses_t0_for_prefix_interval_origin(self) -> None:
        plan = (
            ROOT
            / "docs/superpowers/plans/2026-08-17-jackal-navier-stokes-verification-report.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("prefix intervals with\n`t1 = 0`", plan)
        self.assertIn("prefix intervals with\n`t0 = 0`", plan)

    def test_unbound_generated_output_is_absent(self) -> None:
        self.assertFalse((ROOT / "out/navier_stokes_v1.mono.json").exists())

    def test_halt_alert_exit_code_is_nonzero(self) -> None:
        result = {
            "status": "indeterminate",
            "halt": True,
            "reason": "uncertified_potential_blowup_vortex_stretching",
        }
        self.assertNotEqual(producer_module.receipt_exit_code(result), 0)

    def test_every_nonbounded_result_exit_code_is_nonzero(self) -> None:
        self.assertNotEqual(
            producer_module.receipt_exit_code(
                {"status": "indeterminate", "halt": False, "reason": "not_closed"}
            ),
            0,
        )
        self.assertNotEqual(
            producer_module.receipt_exit_code(
                {"status": "refused", "halt": True, "reason": "not_admitted"}
            ),
            0,
        )
        self.assertEqual(
            producer_module.receipt_exit_code(
                {"status": "bounded", "halt": False, "reason": "closed"}
            ),
            0,
        )

    def test_ratio_alert_cli_writes_receipt_and_exits_three(self) -> None:
        request = gate_b_request(w="3", d="2")
        with tempfile.TemporaryDirectory(prefix="navier-alert-cli-") as temporary:
            temporary_path = Path(temporary)
            request_path = temporary_path / "request.json"
            receipt_path = temporary_path / "receipt.json"
            request_path.write_bytes(canonical_json_bytes(request) + b"\n")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "tools/navier_stokes_certificate_producer.py"),
                    "--request",
                    str(request_path),
                    "--out",
                    str(receipt_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(completed.returncode, 3, completed.stderr + completed.stdout)
        self.assertIn("NAVIER_STOKES_RECEIPT_STATUS=indeterminate", completed.stdout)
        self.assertTrue(receipt["result"]["halt"])
        self.assertEqual(
            receipt["result"]["reason"],
            "uncertified_potential_blowup_vortex_stretching",
        )
        self.assertEqual(receipt["result"]["nonclaim"], "not_evidence_of_singularity")

    def test_programmatic_deep_request_returns_deterministic_codec_refusal(self) -> None:
        request: object = "leaf"
        for _ in range(1100):
            request = [request]
        first = produce_receipt(request, root=ROOT)
        second = produce_receipt(request, root=ROOT)
        self.assertEqual(first, second)
        self.assertEqual(first["authority"]["decision_layer"], "closed_json_codec")
        self.assertEqual(first["result"]["status"], "refused")
        self.assertEqual(first["result"]["reason"], "schema_resource_limit")

    def test_cli_does_not_load_a_request_larger_than_the_request_limit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="navier-cli-request-limit-") as temporary:
            temporary_path = Path(temporary)
            request_path = temporary_path / "oversized.json"
            receipt_path = temporary_path / "receipt.json"
            request_path.write_bytes(b" " * (4_194_304 + 1))
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/navier_stokes_certificate_producer.py"),
                    "--request",
                    str(request_path),
                    "--out",
                    str(receipt_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
            receipt_exists = receipt_path.exists()
        self.assertEqual(completed.returncode, 2)
        self.assertIn("request_input_unavailable", completed.stdout)
        self.assertFalse(receipt_exists)

    def test_manifest_authorizes_only_the_immutable_anubis_pin(self) -> None:
        manifest = json.loads(
            (ROOT / "domain_packs/pde/navier_stokes_v1.json").read_text(encoding="utf-8")
        )
        platform = manifest["platform"]
        self.assertNotIn("anubis_binary_path", platform)
        self.assertEqual(platform["anubis_binary_locator_id"], ANUBIS_LOCATOR_ID)
        self.assertEqual(
            platform["anubis_binary_relative_candidates"],
            ANUBIS_RELATIVE_CANDIDATES,
        )
        self.assertFalse(any(Path(item).is_absolute() for item in ANUBIS_RELATIVE_CANDIDATES))
        self.assertNotIn("/Users/", json.dumps(platform, sort_keys=True))
        self.assertEqual(platform["anubis_binary_sha256"], ANUBIS_SHA256)
        self.assertEqual(platform["anubis_binary_size_bytes"], ANUBIS_SIZE)
        self.assertEqual(hashlib.sha256(PINNED_ANUBIS.read_bytes()).hexdigest(), ANUBIS_SHA256)
        self.assertEqual(PINNED_ANUBIS.stat().st_size, ANUBIS_SIZE)
        self.assertEqual(PINNED_ANUBIS.stat().st_mode & 0o222, 0)

    def test_navier_authority_and_evidence_have_no_host_username_paths(self) -> None:
        for relative in (
            "tools/navier_stokes_certificate_producer.py",
            "tools/navier_stokes_receipt_verify.py",
            "release/evidence/navier_stokes_report_crosswalk.json",
        ):
            with self.subTest(relative=relative):
                self.assertNotIn("/Users/", (ROOT / relative).read_text(encoding="utf-8"))

    def test_mutable_release_path_cannot_self_authorize_with_its_own_digest(self) -> None:
        request = gate_a_request()
        receipt = produce_receipt(request, root=ROOT)
        with tempfile.TemporaryDirectory(prefix="navier-mutable-binary-manifest-") as temporary:
            alternate = Path(temporary)
            for relative in (
                "domain_packs/pde/navier_stokes_v1.anb",
                "domain_packs/pde/navier_stokes_v1.json",
                "domain_packs/pde/representations/T3_ZERO_FOURIER_FIELD_V1.txt",
                "domain_packs/pde/identities/JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1.txt",
                "domain_packs/pde/certificates/JACKAL_T3_ZERO_PROOF_OBJECT_V1.txt",
            ):
                destination = alternate / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, destination)
            manifest_path = alternate / "domain_packs/pde/navier_stokes_v1.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["platform"]["anubis_binary_locator_id"] = (
                "macos-account-home-relative-v1:mutable-anubis"
            )
            manifest["platform"]["anubis_binary_relative_candidates"] = [
                "anubis-lang/target/release/anubis"
            ]
            manifest["platform"]["anubis_binary_sha256"] = hashlib.sha256(
                MUTABLE_ANUBIS.read_bytes()
            ).hexdigest()
            manifest["platform"]["anubis_binary_size_bytes"] = MUTABLE_ANUBIS.stat().st_size
            manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")
            attacker_manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            with mock.patch.object(
                verifier_module,
                "EXPECTED_MANIFEST_SHA256",
                attacker_manifest_sha256,
            ):
                with self.assertRaisesRegex(ReceiptRefusal, "pack_manifest_authority_mismatch"):
                    verify_receipt(receipt, expected_request=request, root=alternate)

    def test_receipt_binary_locator_laundering_to_mutable_release_refuses(self) -> None:
        request = gate_a_request()
        receipt = produce_receipt(request, root=ROOT)
        self.assertNotIn("anubis_binary_path", receipt["authority"])
        self.assertEqual(
            receipt["authority"]["anubis_binary_locator_id"],
            ANUBIS_LOCATOR_ID,
        )
        self.assertEqual(
            receipt["authority"]["anubis_execution_binding"],
            "descriptor_snapshot_v1",
        )
        receipt["authority"]["anubis_binary_locator_id"] = (
            "macos-account-home-relative-v1:mutable-anubis"
        )
        receipt["authority"]["anubis_binary_sha256"] = HISTORICAL_FAILED_MUTABLE_SHA256
        receipt["authority"]["anubis_binary_size_bytes"] = MUTABLE_ANUBIS.stat().st_size
        _repin_receipt(receipt)
        with self.assertRaisesRegex(ReceiptRefusal, "anubis_binary_locator_identity_mismatch"):
            verify_receipt(receipt, expected_request=request, root=ROOT)

    def test_producer_executes_a_private_snapshot_of_pinned_descriptor_bytes(self) -> None:
        calls: list[tuple[list[str], dict]] = []
        original_popen = producer_module.subprocess.Popen

        def capture(args: list[str], *positional: object, **keywords: object):
            calls.append((args, keywords))
            return original_popen(args, *positional, **keywords)

        with mock.patch.object(producer_module.subprocess, "Popen", side_effect=capture):
            receipt = produce_receipt(gate_a_request(), root=ROOT)
        self.assertEqual(len(calls), 1)
        executed = Path(calls[0][0][0])
        native_out = Path(calls[0][0][3])
        source = Path(calls[0][0][4])
        self.assertEqual(executed.name, "anubis-authority.snapshot")
        self.assertEqual(source.name, "navier-stokes-authority.snapshot.anb")
        self.assertNotEqual(executed, PINNED_ANUBIS)
        self.assertNotEqual(executed, MUTABLE_ANUBIS)
        self.assertEqual(native_out.name, "native")
        self.assertEqual(native_out.parent, executed.parent)
        self.assertFalse(native_out.exists())
        self.assertEqual(
            receipt["authority"]["anubis_execution_binding"],
            "descriptor_snapshot_v1",
        )

    def test_subprocess_output_is_bounded_while_the_process_is_running(self) -> None:
        command = [
            sys.executable,
            "-c",
            "import os; os.write(1, b'x' * 8192); os.write(2, b'y' * 8192)",
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        with self.assertRaisesRegex(RuntimeError, "output exceeded"):
            producer_module._communicate_bounded(
                process,
                maximum_output_bytes=1024,
                timeout_seconds=5,
            )

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        with self.assertRaisesRegex(ReceiptRefusal, "anubis_output_resource_limit"):
            verifier_module._communicate_bounded(
                process,
                maximum_output_bytes=1024,
                timeout_seconds=5,
            )

    def test_process_group_permission_error_falls_back_to_direct_kill(self) -> None:
        for module in (producer_module, verifier_module):
            process = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                with mock.patch.object(
                    module.os,
                    "killpg",
                    side_effect=PermissionError(1, "operation not permitted"),
                ):
                    module._terminate_process_group(process)
                self.assertIsNotNone(process.poll())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()

    def test_verifier_ignores_environment_selected_binary(self) -> None:
        request = gate_a_request()
        receipt = produce_receipt(request, root=ROOT)
        false_binary = Path("/usr/bin/true")
        receipt["authority"]["anubis_binary_sha256"] = hashlib.sha256(false_binary.read_bytes()).hexdigest()
        _repin_receipt(receipt)
        with mock.patch.dict(os.environ, {"JACKAL_ANUBIS_BIN": str(false_binary)}):
            with self.assertRaisesRegex(ReceiptRefusal, "anubis_binary_identity_mismatch"):
                verify_receipt(receipt, expected_request=request, root=ROOT)

    def test_missing_manifest_refuses_before_receipt_replay(self) -> None:
        request = gate_a_request()
        receipt = produce_receipt(request, root=ROOT)
        with tempfile.TemporaryDirectory(prefix="navier-missing-manifest-") as temporary:
            alternate = Path(temporary)
            source = alternate / "domain_packs/pde/navier_stokes_v1.anb"
            source.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "domain_packs/pde/navier_stokes_v1.anb", source)
            with self.assertRaisesRegex(ReceiptRefusal, "pack_manifest_unavailable"):
                verify_receipt(receipt, expected_request=request, root=alternate)

    def test_mutated_manifest_and_repinned_receipt_still_refuse(self) -> None:
        request = gate_a_request()
        receipt = produce_receipt(request, root=ROOT)
        with tempfile.TemporaryDirectory(prefix="navier-mutated-manifest-") as temporary:
            alternate = Path(temporary)
            source = alternate / "domain_packs/pde/navier_stokes_v1.anb"
            manifest = alternate / "domain_packs/pde/navier_stokes_v1.json"
            source.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "domain_packs/pde/navier_stokes_v1.anb", source)
            data = json.loads((ROOT / "domain_packs/pde/navier_stokes_v1.json").read_text())
            data["assurance_ceiling"] = "caller_rewritten"
            manifest.write_bytes(canonical_json_bytes(data) + b"\n")
            receipt["authority"]["pack_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
            _repin_receipt(receipt)
            with self.assertRaisesRegex(ReceiptRefusal, "pack_manifest_identity_mismatch"):
                verify_receipt(receipt, expected_request=request, root=alternate)

    def test_mutated_zero_proof_artifact_refuses_under_exact_manifest(self) -> None:
        request = gate_s_request()
        receipt = produce_receipt(request, root=ROOT)
        with tempfile.TemporaryDirectory(prefix="navier-mutated-zero-proof-") as temporary:
            alternate = Path(temporary)
            for relative in (
                "domain_packs/pde/navier_stokes_v1.anb",
                "domain_packs/pde/navier_stokes_v1.json",
                "domain_packs/pde/representations/T3_ZERO_FOURIER_FIELD_V1.txt",
                "domain_packs/pde/identities/JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1.txt",
                "domain_packs/pde/certificates/JACKAL_T3_ZERO_PROOF_OBJECT_V1.txt",
            ):
                destination = alternate / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, destination)
            proof = alternate / "domain_packs/pde/certificates/JACKAL_T3_ZERO_PROOF_OBJECT_V1.txt"
            proof.write_bytes(proof.read_bytes() + b"mutated=true\n")
            with mock.patch.object(
                verifier_module,
                "_execute_anubis",
                return_value=copy.deepcopy(receipt["result"]),
            ):
                with self.assertRaisesRegex(ReceiptRefusal, "proof_object_identity_mismatch"):
                    verify_receipt(receipt, expected_request=request, root=alternate)

    def test_nonregular_manifest_refuses_before_receipt_replay(self) -> None:
        request = gate_a_request()
        receipt = produce_receipt(request, root=ROOT)
        with tempfile.TemporaryDirectory(prefix="navier-nonregular-manifest-") as temporary:
            alternate = Path(temporary)
            manifest = alternate / "domain_packs/pde/navier_stokes_v1.json"
            manifest.mkdir(parents=True)
            with self.assertRaisesRegex(ReceiptRefusal, "pack_manifest_unavailable:nonregular"):
                verify_receipt(receipt, expected_request=request, root=alternate)

    def test_valid_receipt_requires_fresh_anubis_reexecution(self) -> None:
        request = gate_a_request()
        receipt = produce_receipt(request, root=ROOT)
        with mock.patch.object(
            verifier_module,
            "_execute_anubis",
            side_effect=ReceiptRefusal("sentinel_reexecution_required"),
        ):
            with self.assertRaisesRegex(ReceiptRefusal, "sentinel_reexecution_required"):
                verify_receipt(receipt, expected_request=request, root=ROOT)

    def test_independent_replay_rejects_even_runtime_aligned_status_laundering(self) -> None:
        request = gate_b_request(w="1", d="2")
        receipt = produce_receipt(request, root=ROOT)
        receipt["result"].update(
            status="bounded",
            reason="caller_laundered",
            solution_link_status="SOLUTION_LINK_VERIFIED",
            conclusion_status="BOUNDED_ON_SCOPE",
        )
        _repin_receipt(receipt)
        with mock.patch.object(
            verifier_module,
            "_execute_anubis",
            return_value=copy.deepcopy(receipt["result"]),
        ):
            with self.assertRaisesRegex(ReceiptRefusal, "independent_replay_mismatch"):
                verify_receipt(receipt, expected_request=request, root=ROOT)

    def test_codec_refusal_receipt_replays_without_admitted_request(self) -> None:
        request = gate_a_request()
        request["surprise"] = True
        receipt = produce_receipt(request, root=ROOT)
        self.assertEqual(receipt["authority"]["decision_layer"], "closed_json_codec")
        verified = verify_receipt(receipt, expected_request=request, root=ROOT)
        self.assertEqual(verified["receipt_sha256"], receipt["receipt_sha256"])

    def test_codec_reason_parity_for_type_delimiter_and_integer_limits(self) -> None:
        mutations = []
        wrong_type = gate_a_request()
        wrong_type["model"]["density"] = 1
        mutations.append((wrong_type, "schema_type_mismatch"))
        delimiter = gate_a_request()
        delimiter["scope"]["terminal_role"] = "finite|scope"
        mutations.append((delimiter, "protocol_delimiter_injection"))
        integer_limit = gate_s_request()
        integer_limit["solution_link"]["m"] = 1_000_001
        mutations.append((integer_limit, "schema_resource_limit"))
        for request, reason in mutations:
            with self.subTest(reason=reason):
                receipt = produce_receipt(request, root=ROOT)
                self.assertEqual(receipt["result"]["reason"], reason)
                verified = verify_receipt(receipt, expected_request=request, root=ROOT)
                self.assertEqual(verified["receipt_sha256"], receipt["receipt_sha256"])

    def test_duplicate_key_codec_refusal_receipt_replays(self) -> None:
        raw = b'{"schema":"a","schema":"b"}\n'
        receipt = producer_module.produce_receipt_from_json_bytes(raw, root=ROOT)
        self.assertEqual(receipt["result"]["reason"], "schema_duplicate_field")
        verified = verifier_module.verify_receipt_bytes(
            receipt,
            expected_request_bytes=raw,
            root=ROOT,
        )
        self.assertEqual(verified["receipt_sha256"], receipt["receipt_sha256"])

    def test_malformed_json_codec_refusal_receipt_replays(self) -> None:
        raw = b'{"schema":]\n'
        receipt = producer_module.produce_receipt_from_json_bytes(raw, root=ROOT)
        self.assertEqual(receipt["result"]["reason"], "schema_invalid_json")
        verified = verifier_module.verify_receipt_bytes(
            receipt,
            expected_request_bytes=raw,
            root=ROOT,
        )
        self.assertEqual(verified["receipt_sha256"], receipt["receipt_sha256"])

    def test_oversized_json_codec_refusal_receipt_replays(self) -> None:
        raw = b" " * (4_194_304 + 1)
        receipt = producer_module.produce_receipt_from_json_bytes(raw, root=ROOT)
        self.assertEqual(receipt["result"]["reason"], "schema_resource_limit")
        verified = verifier_module.verify_receipt_bytes(
            receipt,
            expected_request_bytes=raw,
            root=ROOT,
        )
        self.assertEqual(verified["receipt_sha256"], receipt["receipt_sha256"])

    def test_json_depth_limit_codec_refusal_receipt_replays(self) -> None:
        raw = ("[" * 33 + "0" + "]" * 33).encode("ascii")
        receipt = producer_module.produce_receipt_from_json_bytes(raw, root=ROOT)
        self.assertEqual(receipt["result"]["reason"], "schema_resource_limit")
        verified = verifier_module.verify_receipt_bytes(
            receipt,
            expected_request_bytes=raw,
            root=ROOT,
        )
        self.assertEqual(verified["receipt_sha256"], receipt["receipt_sha256"])

    def test_json_node_limit_codec_refusal_receipt_replays(self) -> None:
        raw = json.dumps([0] * 4097, separators=(",", ":")).encode("ascii")
        receipt = producer_module.produce_receipt_from_json_bytes(raw, root=ROOT)
        self.assertEqual(receipt["result"]["reason"], "schema_resource_limit")
        verified = verifier_module.verify_receipt_bytes(
            receipt,
            expected_request_bytes=raw,
            root=ROOT,
        )
        self.assertEqual(verified["receipt_sha256"], receipt["receipt_sha256"])

    def test_duplicate_key_codec_refusal_cli_round_trip(self) -> None:
        raw = b'{"schema":"a","schema":"b"}\n'
        with tempfile.TemporaryDirectory(prefix="navier-codec-cli-") as temporary:
            temporary_path = Path(temporary)
            request_path = temporary_path / "request.json"
            receipt_path = temporary_path / "receipt.json"
            request_path.write_bytes(raw)
            produced = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "tools/navier_stokes_certificate_producer.py"),
                    "--request",
                    str(request_path),
                    "--out",
                    str(receipt_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(produced.returncode, 2, produced.stderr)
            self.assertTrue(receipt_path.is_file(), produced.stderr)
            verified = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "tools/navier_stokes_receipt_verify.py"),
                    "--receipt",
                    str(receipt_path),
                    "--expected-request",
                    str(request_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(verified.returncode, 0, verified.stderr + verified.stdout)
        self.assertIn("NAVIER_STOKES_RECEIPT_VERIFY=PASS", verified.stdout)

    def test_direct_kernel_rejects_more_than_128_cutoffs(self) -> None:
        request = gate_b_request(w="0", d="1")
        template = request["gate_data"]["cutoffs"][0]
        request["gate_data"]["cutoffs"] = [
            {**copy.deepcopy(template), "lambda": str(index + 1)}
            for index in range(129)
        ]
        result = _direct_anubis_result(request)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "cutoff_resource_limit_exceeded")

    def test_direct_kernel_rejects_noncanonical_theorem_digest(self) -> None:
        request = gate_s_request()
        request["solution_link"]["theorem_source_sha256"] = "A" * 64
        result = _direct_anubis_result(request)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "schema_invalid_digest")

    def test_computed_ratio_above_resource_bound_refuses(self) -> None:
        request = gate_b_request(w="1000000000", d="1")
        request["model"]["viscosity"] = "1/1000000000"
        result = produce_receipt(request, root=ROOT)["result"]
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "rational_resource_bound_exceeded")

    def test_direct_kernel_rejects_atom_above_4096_bytes(self) -> None:
        request = gate_s_request()
        request["scope"]["terminal_role"] = "x" * 4097
        result = _direct_anubis_result(request)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "atom_resource_limit_exceeded")

    def test_direct_kernel_counts_utf8_bytes_not_codepoints(self) -> None:
        request = gate_s_request()
        request["scope"]["terminal_role"] = "é" * 3000
        result = _direct_anubis_result(request)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "atom_resource_limit_exceeded")

    def test_zero_lane_uses_one_distinct_proof_object(self) -> None:
        solution = gate_s_request()["solution_link"]
        self.assertIn("proof_object_id", solution)
        self.assertIn("proof_object_digest", solution)
        for obsolete in (
            "pde_residual_digest",
            "initial_mismatch_digest",
            "divergence_digest",
            "dependency_graph_digest",
            "threshold_certificate_digest",
        ):
            self.assertNotIn(obsolete, solution)
        self.assertNotEqual(solution["proof_object_digest"], solution["theorem_source_sha256"])
        self.assertNotEqual(solution["proof_object_digest"], gate_s_request()["scope"]["reconstruction_digest"])
        artifacts = {
            "representation": ROOT / "domain_packs/pde/representations/T3_ZERO_FOURIER_FIELD_V1.txt",
            "theorem": ROOT / "domain_packs/pde/identities/JACKAL_T3_ZERO_SOLUTION_IDENTITY_V1.txt",
            "proof": ROOT / "domain_packs/pde/certificates/JACKAL_T3_ZERO_PROOF_OBJECT_V1.txt",
        }
        digests = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in artifacts.items()}
        self.assertEqual(digests["representation"], gate_s_request()["scope"]["reconstruction_digest"])
        self.assertEqual(digests["theorem"], solution["theorem_source_sha256"])
        self.assertEqual(digests["proof"], solution["proof_object_digest"])
        self.assertEqual(len(set(digests.values())), 3)

    def test_report_crosswalk_prevents_status_and_viscosity_laundering(self) -> None:
        crosswalk = json.loads(
            (ROOT / "release/evidence/navier_stokes_report_crosswalk.json").read_text(
                encoding="utf-8"
            )
        )
        runtime = crosswalk["repository_runtime_authority"]
        self.assertEqual(runtime["anubis_binary_locator_id"], ANUBIS_LOCATOR_ID)
        self.assertEqual(
            runtime["anubis_binary_relative_candidates"],
            ANUBIS_RELATIVE_CANDIDATES,
        )
        self.assertEqual(runtime["anubis_binary_sha256"], ANUBIS_SHA256)
        self.assertEqual(runtime["anubis_binary_size_bytes"], ANUBIS_SIZE)
        self.assertEqual(runtime["anubis_execution_binding"], "descriptor_snapshot_v1")
        self.assertFalse(runtime["mutable_target_release_is_authoritative"])
        self.assertEqual(
            runtime["historical_failed_mutable_sha256"],
            HISTORICAL_FAILED_MUTABLE_SHA256,
        )
        semantics = crosswalk["dissipation_semantics"]
        self.assertEqual(
            semantics["external_report_dissipation_lower"],
            "already_viscosity_weighted_lower_bound",
        )
        self.assertEqual(
            semantics["repository_d_truncated"],
            "unweighted_dissipation_enclosure",
        )
        self.assertEqual(
            semantics["repository_denominator"],
            "nu*(lower(d_truncated)-upper(d_tail_upper))",
        )
        self.assertTrue(semantics["forbid_direct_field_equivalence"])
        mappings = {item["external_status"]: item for item in crosswalk["status_crosswalk"]}
        self.assertEqual(mappings["ARITHMETIC_CHECKED"]["repository_status"], "refused")
        self.assertEqual(mappings["refused"]["repository_status"], "indeterminate")
        self.assertTrue(mappings["refused"]["repository_halt"])
        self.assertEqual(mappings["BOUNDED_ON_SCOPE"]["repository_gate"], "gate_s")
        self.assertIn("not_evidence_of_singularity", crosswalk["permanent_nonclaims"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
