from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import copy
from contextlib import redirect_stdout
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zlib
from io import BytesIO, StringIO
from pathlib import Path
from types import ModuleType
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "release/tools/package_spacecraft_v175.py"


def load_packager():
    spec = importlib.util.spec_from_file_location("spacecraft_v175_packager", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load v1.7.5 release packager")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_current_claim_validator(package):
    return package.load_claim_validator(
        (ROOT / package.CLAIM_GATE_LOGICAL_PATH).read_bytes()
    )


class SpacecraftReleasePackageV175Tests(unittest.TestCase):
    def test_frozen_github_release_metadata_is_bound_and_claim_scanned(self):
        package = load_packager()
        metadata_bytes = (ROOT / package.RELEASE_METADATA_LOGICAL_PATH).read_bytes()
        notes_bytes = (ROOT / package.RELEASE_NOTES_LOGICAL_PATH).read_bytes()
        claim_validator = load_current_claim_validator(package)
        metadata = package.validate_release_metadata(
            metadata_bytes,
            notes_bytes,
            claim_validator,
        )
        self.assertEqual(metadata["tag"], package.VERSION)
        self.assertEqual(metadata["notes_path"], package.RELEASE_NOTES_LOGICAL_PATH)
        self.assertEqual(metadata["notes_sha256"], package.sha256(notes_bytes))
        self.assertEqual(
            metadata["title"],
            "JACKAL v1.7.5 - Spacecraft finite-burn certification",
        )
        self.assertIn(
            package.RELEASE_METADATA_LOGICAL_PATH,
            package.STATIC_TRACKED_INPUT_PATHS,
        )
        self.assertIn(
            package.RELEASE_NOTES_LOGICAL_PATH,
            package.STATIC_TRACKED_INPUT_PATHS,
        )
        mutant = {**metadata, "title": "CERTIFIED SAFE"}
        mutant_bytes = (
            json.dumps(mutant, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        with self.assertRaisesRegex(RuntimeError, "release metadata claim surface"):
            package.validate_release_metadata(
                mutant_bytes,
                notes_bytes,
                claim_validator,
            )

    def test_preimport_aba_cannot_supply_resident_release_dependencies(self):
        fake_legacy = ModuleType("release.tools.package_spacecraft_v174")
        fake_legacy.WITNESS_NAME = "mutant.cert"
        fake_legacy.RECEIPT_NAME = "mutant.json"
        fake_legacy.PROOF_NAME = "mutant-proof.json"
        fake_legacy.SPACECRAFT_REQUEST_DIGEST = "0" * 64
        fake_legacy.AUXILIARY_EVIDENCE_NAMES = ()
        fake_legacy.sha256 = lambda _data: "0" * 64
        fake_legacy.deterministic_tar_gz = lambda _entries: b"mutant archive"
        fake_legacy.validate_witness_digests = lambda *_args: None
        fake_legacy.validate_request_binding = lambda *_args: None
        fake_claim_gate = ModuleType("tools.spacecraft_burn_release_gate")
        fake_claim_gate.QUALIFIED_VERDICT = "MUTANT VERDICT"
        with mock.patch.dict(
            sys.modules,
            {
                "release.tools.package_spacecraft_v174": fake_legacy,
                "tools.spacecraft_burn_release_gate": fake_claim_gate,
            },
        ):
            package = load_packager()
        self.assertEqual(package.WITNESS_NAME, "baseline_witness_v2.cert")
        self.assertEqual(package.RECEIPT_NAME, "baseline_receipt_v2.json")
        self.assertEqual(
            package.QUALIFIED_VERDICT,
            "CERTIFIED SAFE under the stated finite-burn ODE model, supplied "
            "input bounds, and machine-checked interval-certificate assumptions",
        )
        self.assertFalse(hasattr(package, "legacy"))
        self.assertFalse(hasattr(package, "claim_gate"))

    def test_git_invocations_ignore_hostile_path(self):
        package = load_packager()
        with tempfile.TemporaryDirectory() as directory:
            hostile = Path(directory) / "git"
            hostile.write_text("#!/bin/sh\necho MALICIOUS_GIT\n")
            hostile.chmod(0o755)
            with mock.patch.dict(
                os.environ,
                {
                    "PATH": directory,
                    "GIT_DIR": str(Path(directory) / "forged-git-dir"),
                    "GIT_OBJECT_DIRECTORY": str(
                        Path(directory) / "forged-objects"
                    ),
                    "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(
                        Path(directory) / "forged-alternates"
                    ),
                    "GIT_CONFIG_GLOBAL": str(
                        Path(directory) / "forged-config"
                    ),
                },
            ):
                result = package._git(["--version"])
                head = package._git(["rev-parse", "HEAD"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("git version", result.stdout)
        self.assertNotIn("MALICIOUS_GIT", result.stdout)
        self.assertEqual(head.returncode, 0, head.stderr)
        self.assertRegex(head.stdout.strip(), r"^[0-9a-f]{40}$")

    def test_raw_commit_and_tree_objects_are_hash_bound(self):
        package = load_packager()
        commit = package._git(["rev-parse", "HEAD"]).stdout.strip()
        expected_tree = package._git(
            ["rev-parse", f"{commit}^{{tree}}"]
        ).stdout.strip()
        self.assertEqual(package._resolve_git_commit(commit, "test"), expected_tree)

    def test_git_replacement_objects_are_rejected(self):
        package = load_packager()
        git = "/usr/bin/git"
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            subprocess.run([git, "init", "-q", str(repository)], check=True)
            subprocess.run(
                [git, "-C", str(repository), "config", "user.name", "Test"],
                check=True,
            )
            subprocess.run(
                [git, "-C", str(repository), "config", "user.email", "test@example.invalid"],
                check=True,
            )
            (repository / "value.txt").write_text("one\n")
            subprocess.run([git, "-C", str(repository), "add", "value.txt"], check=True)
            subprocess.run([git, "-C", str(repository), "commit", "-qm", "one"], check=True)
            first = subprocess.run(
                [git, "-C", str(repository), "rev-parse", "HEAD"],
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
            (repository / "value.txt").write_text("two\n")
            subprocess.run([git, "-C", str(repository), "commit", "-qam", "two"], check=True)
            second = subprocess.run(
                [git, "-C", str(repository), "rev-parse", "HEAD"],
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
            subprocess.run(
                [git, "-C", str(repository), "replace", first, second], check=True
            )
            with mock.patch.object(package, "ROOT", repository):
                with self.assertRaisesRegex(RuntimeError, "replacement object"):
                    package.validate_git_repository_provenance()

    def test_reachable_git_blob_corruption_is_rejected(self):
        package = load_packager()
        git = "/usr/bin/git"
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            subprocess.run([git, "init", "-q", str(repository)], check=True)
            subprocess.run(
                [git, "-C", str(repository), "config", "user.name", "Test"],
                check=True,
            )
            subprocess.run(
                [git, "-C", str(repository), "config", "user.email", "test@example.invalid"],
                check=True,
            )
            tracked = repository / "value.txt"
            tracked.write_text("trusted\n")
            subprocess.run([git, "-C", str(repository), "add", "value.txt"], check=True)
            subprocess.run([git, "-C", str(repository), "commit", "-qm", "one"], check=True)
            commit = subprocess.run(
                [git, "-C", str(repository), "rev-parse", "HEAD"],
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
            blob = subprocess.run(
                [git, "-C", str(repository), "rev-parse", "HEAD:value.txt"],
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
            loose_object = repository / ".git" / "objects" / blob[:2] / blob[2:]
            mutant_body = b"mutated\n"
            loose_object.chmod(0o644)
            loose_object.write_bytes(
                zlib.compress(b"blob " + str(len(mutant_body)).encode() + b"\0" + mutant_body)
            )
            with mock.patch.object(package, "ROOT", repository):
                with self.assertRaisesRegex(RuntimeError, "object integrity"):
                    package.validate_git_release_binding(commit, commit)

    def test_command_bearing_local_git_config_is_never_executed(self):
        package = load_packager()
        git = "/usr/bin/git"
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            subprocess.run([git, "init", "-q", str(repository)], check=True)
            subprocess.run(
                [git, "-C", str(repository), "config", "user.name", "Test"],
                check=True,
            )
            subprocess.run(
                [git, "-C", str(repository), "config", "user.email", "test@example.invalid"],
                check=True,
            )
            (repository / "value.txt").write_text("trusted\n")
            subprocess.run([git, "-C", str(repository), "add", "value.txt"], check=True)
            subprocess.run([git, "-C", str(repository), "commit", "-qm", "one"], check=True)
            commit = subprocess.run(
                [git, "-C", str(repository), "rev-parse", "HEAD"],
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
            marker = repository / ".git" / "fsmonitor-ran"
            hook = repository / ".git" / "hostile-fsmonitor.sh"
            hook.write_text(
                "#!/bin/sh\n"
                f"/usr/bin/touch {marker}\n"
                "exit 0\n"
            )
            hook.chmod(0o755)
            subprocess.run(
                [git, "-C", str(repository), "config", "core.fsmonitor", str(hook)],
                check=True,
            )
            with mock.patch.object(package, "ROOT", repository):
                with self.assertRaisesRegex(
                    RuntimeError, "command-bearing local Git config"
                ):
                    package.validate_git_release_binding(commit, commit)
            self.assertFalse(marker.exists())

    def test_atomic_write_retries_until_every_byte_is_persisted(self):
        package = load_packager()
        payload = b"release asset bytes that require several writes"
        original_write = package.os.write
        write_sizes = []

        def partial_write(descriptor, data):
            chunk = data[: max(1, len(data) // 2)]
            written = original_write(descriptor, chunk)
            write_sizes.append(written)
            return written

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "asset.bin"
            with mock.patch.object(package.os, "write", side_effect=partial_write):
                package.atomic_write(target, payload)
            self.assertEqual(target.read_bytes(), payload)
            self.assertGreater(len(write_sizes), 1)

    def test_atomic_write_removes_temporary_file_after_failure(self):
        package = load_packager()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "asset.bin"
            with mock.patch.object(
                package.os, "write", side_effect=OSError("simulated failure")
            ):
                with self.assertRaisesRegex(OSError, "simulated failure"):
                    package.atomic_write(target, b"release asset")
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_bounded_live_reader_rejects_symlink_fifo_and_oversize(self):
        package = load_packager()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regular = root / "regular.bin"
            regular.write_bytes(b"12345")
            symlink = root / "symlink.bin"
            symlink.symlink_to(regular)
            fifo = root / "fifo.bin"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(RuntimeError, "regular file"):
                package.read_bounded_regular_file(
                    symlink, "test symlink", 16
                )
            with self.assertRaisesRegex(RuntimeError, "regular file"):
                package.read_bounded_regular_file(fifo, "test fifo", 16)
            with self.assertRaisesRegex(RuntimeError, "size limit"):
                package.read_bounded_regular_file(
                    regular, "test oversized file", 4
                )
            self.assertEqual(
                package.read_bounded_regular_file(regular, "test file", 5),
                b"12345",
            )

    def test_packager_runs_directly_from_outside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "sitecustomize-ran"
            hostile = Path(directory) / "hostile-python"
            hostile.mkdir()
            (hostile / "sitecustomize.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n"
            )
            result = subprocess.run(
                ["/usr/bin/python3", "-I", "-B", str(SCRIPT), "--help"],
                cwd=directory,
                env={**os.environ, "PYTHONPATH": str(hostile)},
                text=True,
                capture_output=True,
            )
            self.assertFalse(marker.exists())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--reviewed-commit", result.stdout)
        self.assertIn(
            "/usr/bin/python3 -I -B release/tools/package_spacecraft_v175.py",
            " ".join(result.stdout.split()),
        )

    def test_publication_entrypoint_rejects_nonisolated_python(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                ["/usr/bin/python3", "-B", str(SCRIPT), "--help"],
                cwd=directory,
                text=True,
                capture_output=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("/usr/bin/python3 -I -B", result.stderr)

    @unittest.skipUnless(
        Path("/Library/Developer/CommandLineTools/usr/bin/python3").is_file(),
        "Command Line Tools Python is unavailable",
    )
    def test_publication_entrypoint_rejects_unbound_alternate_python(self):
        alternate = "/Library/Developer/CommandLineTools/usr/bin/python3"
        result = subprocess.run(
            [alternate, "-I", "-B", str(SCRIPT), "--help"],
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("proof identity", result.stderr)

    def test_publication_runtime_binds_live_git_client(self):
        package = load_packager()
        identity = json.loads(package.IDENTITY.read_text(encoding="utf-8"))
        rows = identity["build_attestation"]["build_environment"][
            "trusted_platform_launchers"
        ]
        interpreter = next(row for row in rows if row["role"] == "python-interpreter")
        with mock.patch.object(package.sys, "executable", interpreter["invocation_path"]):
            runtime = package.validate_publication_runtime(identity)
            self.assertEqual(runtime["git_path"], "/usr/bin/git")
            git_row = next(row for row in rows if row["role"] == "git-client")
            git_row["sha256"] = "0" * 64
            with self.assertRaisesRegex(RuntimeError, "proof identity"):
                package.validate_publication_runtime(identity)

    def test_success_report_uses_observed_runtime_identity(self):
        package = load_packager()
        runtime = {
            "launcher_path": "/usr/bin/python3",
            "launcher_sha256": "1" * 64,
            "interpreter_path": "/Applications/Xcode/usr/bin/python3",
            "interpreter_resolved_path": "/Applications/Xcode/python3.9",
            "interpreter_sha256": "2" * 64,
            "git_path": "/usr/bin/git",
            "git_sha256": "3" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "assets"
            stream = StringIO()
            with (
                mock.patch.object(
                    package,
                    "validate_publication_startup",
                    return_value=runtime,
                ),
                mock.patch.object(package, "build", return_value={"asset": "digest"}),
                redirect_stdout(stream),
            ):
                status = package.main([
                    "--staging-dir",
                    str(root),
                    "--output-dir",
                    str(output),
                    "--merge-commit",
                    "a" * 40,
                    "--reviewed-commit",
                    "b" * 40,
                ])
        report = stream.getvalue()
        self.assertEqual(status, 0)
        self.assertIn(f"python_interpreter={runtime['interpreter_path']}", report)
        self.assertIn(f"python_resolved={runtime['interpreter_resolved_path']}", report)
        self.assertIn(f"python_sha256={runtime['interpreter_sha256']}", report)
        self.assertIn(f"git_sha256={runtime['git_sha256']}", report)
        self.assertNotIn(" python=/usr/bin/python3 ", report)

    def test_release_claim_scan_rejects_json_object_keys(self):
        package = load_packager()
        claim_validator = load_current_claim_validator(package)
        payload = json.dumps({"nested": {"PROVED SAFE": False}}).encode()
        with self.assertRaisesRegex(RuntimeError, "claim surface"):
            package.assert_release_claims(
                package.RECEIPT_NAME,
                payload,
                claim_validator,
            )

    def test_release_and_certificate_epoch_are_v175(self):
        package = load_packager()
        self.assertEqual(package.VERSION, "v1.7.5")
        self.assertEqual(package.CERTIFICATE_EPOCH, "v1.7.5")
        self.assertEqual(
            package.ARCHIVE_NAME,
            "jackal-spacecraft-burn-v1.7.5-verifier-macos-arm64.tar.gz",
        )

    def test_v175_packager_rejects_v174_receipt_epoch(self):
        package = load_packager()
        binding = {
            "request_digest": package.SPACECRAFT_REQUEST_DIGEST,
            "model_id": package.MODEL_ID,
            "epoch": "v1.7.4",
            "nonce": package.PUBLICATION_NONCE,
        }
        with self.assertRaisesRegex(RuntimeError, "release binding"):
            package.validate_release_binding(binding)

    def test_archive_contains_exact_producer_source_for_outer_replay(self):
        package = load_packager()
        recorded_identity = json.loads(package.IDENTITY.read_text())
        recorded_generator = recorded_identity["generator"]
        generator_bytes = (
            ROOT / "release/tools/spacecraft_burn_proof_identity.py"
        ).read_bytes()
        generator_engine_bytes = (
            ROOT / "release/tools/gaussian_proof_identity.py"
        ).read_bytes()
        self.assertEqual(
            recorded_generator,
            {
                "definition": package.GENERATOR_CLOSURE_DEFINITION,
                "files": [
                    {
                        "path": package.GENERATOR_LOGICAL_PATH,
                        "sha256": hashlib.sha256(generator_bytes).hexdigest(),
                    },
                    {
                        "path": package.GENERATOR_ENGINE_LOGICAL_PATH,
                        "sha256": hashlib.sha256(
                            generator_engine_bytes
                        ).hexdigest(),
                    },
                ],
            },
        )
        closure_path = "proofs/lean/lean-toolchain"
        closure_bytes = (ROOT / closure_path).read_bytes()
        identity = {
            "generator": recorded_generator,
            "source_closure": {
                "files": [{
                    "path": closure_path,
                    "bytes": len(closure_bytes),
                    "sha256": hashlib.sha256(closure_bytes).hexdigest(),
                }]
            }
        }
        producer_source = (ROOT / "spacecraft_burn_cert/certify.py").read_bytes()
        tracked_paths = (
            package.VERIFIER_LOGICAL_PATH,
            package.WITNESS_CODEC_LOGICAL_PATH,
            "proofs/lean/lean-toolchain",
            "proofs/lean/lakefile.toml",
            "proofs/lean/lake-manifest.json",
            package.GENERATOR_LOGICAL_PATH,
            package.GENERATOR_ENGINE_LOGICAL_PATH,
        )
        tracked = {path: (ROOT / path).read_bytes() for path in tracked_paths}
        entries = package.archive_entries(
            b"checker", b"identity", identity,
            (ROOT / "spacecraft_burn_cert/request_v2.json").read_bytes(),
            producer_source,
            tracked,
        )
        prefix = "jackal-spacecraft-burn-v1.7.5-verifier-macos-arm64"
        producer = f"{prefix}/producer/certify.py"
        generator = f"{prefix}/release/tools/spacecraft_burn_proof_identity.py"
        generator_engine = f"{prefix}/release/tools/gaussian_proof_identity.py"
        self.assertEqual(entries[producer][0], producer_source)
        self.assertEqual(entries[producer][1], 0o644)
        self.assertEqual(
            entries[generator][0],
            generator_bytes,
        )
        self.assertEqual(
            entries[generator_engine][0],
            generator_engine_bytes,
        )
        archive = package.deterministic_tar_gz(entries)
        with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as opened:
            self.assertIn(producer, opened.getnames())
            self.assertIn(generator, opened.getnames())
            self.assertIn(generator_engine, opened.getnames())

    def test_source_closure_cannot_misclassify_a_committed_local_import(self):
        package = load_packager()
        identity = json.loads(package.IDENTITY.read_text())
        closure = copy.deepcopy(identity["source_closure"])
        omitted_module = "JackalIv.Spacecraft.Interval"
        closure["files"] = [
            row for row in closure["files"] if row["module"] != omitted_module
        ]
        closure["external_imports"] = sorted(
            {*closure["external_imports"], omitted_module}
        )
        committed_paths = set(
            subprocess.run(
                [
                    "/usr/bin/git",
                    "-C",
                    str(ROOT),
                    "ls-tree",
                    "-r",
                    "--name-only",
                    "HEAD",
                    "--",
                    "proofs/lean",
                ],
                check=True,
                text=True,
                capture_output=True,
            ).stdout.splitlines()
        )
        self.assertIn("proofs/lean/JackalIv/Spacecraft/Interval.lean", committed_paths)
        with self.assertRaisesRegex(RuntimeError, "local Lean import"):
            package.validate_source_closure_classification(
                closure, committed_paths
            )

    def test_source_closure_rejects_case_alias_of_a_local_module(self):
        package = load_packager()
        root_module = "JackalIv.Spacecraft.CertMain"
        hidden_module = "JackalIv.Spacecraft.Hidden"
        root_path = "proofs/lean/JackalIv/Spacecraft/CertMain.lean"
        closure = {
            "root_modules": [root_module],
            "external_imports": [hidden_module],
            "files": [
                {
                    "bytes": 1,
                    "imports": [hidden_module],
                    "module": root_module,
                    "path": root_path,
                    "sha256": "0" * 64,
                }
            ],
        }
        committed_paths = {
            root_path,
            "proofs/lean/JackalIv/Spacecraft/hidden.lean",
        }
        with self.assertRaisesRegex(RuntimeError, "local Lean import"):
            package.validate_source_closure_classification(
                closure, committed_paths
            )

    def test_noncanonical_inline_lean_import_is_rejected(self):
        package = load_packager()
        with self.assertRaisesRegex(RuntimeError, "unsupported import syntax"):
            package.parse_committed_lean_imports(
                "proofs/lean/JackalIv/Spacecraft/Hidden.lean",
                b"prelude import JackalIv.Spacecraft.Interval\n",
            )

    def test_verification_instructions_are_copy_paste_complete(self):
        package = load_packager()
        binding = {
            "request_digest": "f" * 64,
            "model_id": package.MODEL_ID,
            "epoch": package.CERTIFICATE_EPOCH,
            "nonce": package.PUBLICATION_NONCE,
        }
        text = package.verification_text(
            "a" * 40,
            "1" * 40,
            "b" * 64,
            "c" * 64,
            "d" * 64,
            "e" * 64,
            "2" * 64,
            "3" * 64,
            binding,
        ).decode()
        self.assertIn("shasum -a 256 -c SHA256SUMS", text)
        self.assertIn(f"tar -xzf {package.ARCHIVE_NAME}", text)
        self.assertLess(text.index("set -eu"), text.index("shasum -a 256"))
        self.assertLess(text.index("shasum -a 256"), text.index("tar -xzf"))
        self.assertLess(text.index('test ! -e "$ARCHIVE_ROOT"'), text.index("tar -xzf"))
        self.assertIn('"$ARCHIVE_ROOT/bin/jackal_spacecraft_burn_check"', text)
        self.assertIn('/usr/bin/python3 -I -B "$ARCHIVE_ROOT/verifier/verify_receipt.py"', text)
        self.assertIn('--source "$ARCHIVE_ROOT/producer/certify.py"', text)
        self.assertIn('--request "$ARCHIVE_ROOT/request_v2.json"', text)
        for flag in (
            "--witness", "--checker", "--proof-identity",
            "--expected-receipt-sha256", "--expected-proof-file-sha256",
            "--expected-proof-identity-sha256", "--expected-request-digest",
            "--expected-model-id", "--expected-epoch", "--nonce",
        ):
            self.assertIn(flag, text)
        for value in (
            "b" * 64,
            "c" * 64,
            "d" * 64,
            "e" * 64,
            "f" * 64,
            "2" * 64,
            "3" * 64,
        ):
            self.assertIn(value, text)
        self.assertNotIn("/absolute/path", text)
        normalized = " ".join(text.split())
        self.assertIn("release merge commit `" + "a" * 40 + "`", normalized)
        self.assertIn("reviewed source commit `" + "1" * 40 + "`", normalized)
        self.assertIn("internal independent code review (not external peer review)", normalized)
        self.assertIn("integrity only; it is not a signature", normalized)
        self.assertIn("direct checker command is diagnostic", normalized)
        self.assertIn("outer verifier is authoritative", normalized)
        self.assertIn(package.QUALIFIED_VERDICT, normalized)

    def test_producer_source_digest_is_bound_to_receipt(self):
        package = load_packager()
        expected = b"exact reviewed producer bytes"
        receipt = {"source_sha256": hashlib.sha256(expected).hexdigest()}
        package.validate_producer_source(receipt, expected)
        with self.assertRaisesRegex(RuntimeError, "producer source digest"):
            package.validate_producer_source(receipt, b"different bytes")
        for malformed in ({}, {"source_sha256": "not-a-digest"}):
            with self.subTest(receipt=malformed), self.assertRaisesRegex(
                RuntimeError, "producer source digest"
            ):
                package.validate_producer_source(malformed, expected)

    def test_staged_baseline_is_bound_to_committed_receipt_and_witness_manifest(self):
        package = load_packager()
        witness = b"exact committed witness"
        receipt = {
            "formal_checker": {"witness_sha256": hashlib.sha256(witness).hexdigest()},
            "witness": {"sha256": hashlib.sha256(witness).hexdigest()},
        }
        receipt_bytes = json.dumps(receipt, sort_keys=True).encode()
        manifest = {
            "schema": "spacecraft-finite-burn-witness-manifest-v2",
            "release_asset": package.WITNESS_NAME,
            "sha256": hashlib.sha256(witness).hexdigest(),
            "byte_size": len(witness),
            "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "formal_checker": receipt["formal_checker"],
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
        expected = {
            package.RECEIPT_NAME: hashlib.sha256(receipt_bytes).hexdigest(),
            package.WITNESS_MANIFEST_NAME: hashlib.sha256(manifest_bytes).hexdigest(),
        }
        package.validate_committed_baseline(
            receipt_bytes, witness, receipt, expected, manifest_bytes
        )
        with self.assertRaisesRegex(RuntimeError, "committed baseline"):
            package.validate_committed_baseline(
                receipt_bytes + b"\n", witness, receipt, expected, manifest_bytes
            )
        with self.assertRaisesRegex(RuntimeError, "committed witness manifest"):
            package.validate_committed_baseline(
                receipt_bytes, witness + b"mutation", receipt, expected, manifest_bytes
            )

    def test_packager_requires_formally_accepted_baseline_receipt(self):
        package = load_packager()
        current = json.loads(
            (ROOT / "spacecraft_burn_cert/evidence/baseline_receipt_v2.json").read_text()
        )
        claim_validator = load_current_claim_validator(package)
        package.validate_formal_receipt(current, claim_validator)
        receipt = {
            "schema": "spacecraft-finite-burn-formal-receipt-v2",
            "verdict": "CERTIFIED SAFE",
            "verdict_qualifier": package.MODEL_QUALIFIER,
            "producer_assurance": "candidate-only",
            "formal_checker_status": "NOT_EXECUTED",
            "evidence_classification": {
                "overall": "rigorously interval-bounded, not formal-bounded"
            },
            "formal_checker": {},
        }
        with self.assertRaisesRegex(RuntimeError, "formally accepted baseline"):
            package.validate_formal_receipt(receipt, claim_validator)

    def test_packager_rejects_unqualified_structured_evidence(self):
        package = load_packager()
        bad = json.dumps({
            "schema": "spacecraft-finite-burn-instrument-validation-v2",
            "step_refinement": {"runs": [{"verdict": "CERTIFIED SAFE"}]},
        }).encode()
        with self.assertRaisesRegex(RuntimeError, "claim surface"):
            package.assert_release_claims(
                "instrument_validation_v2.json",
                bad,
                load_current_claim_validator(package),
            )

    def test_package_json_entrypoints_share_bounded_strict_parser(self):
        package = load_packager()
        malformed = (
            b"[" * 5000 + b"0" + b"]" * 5000,
            b'{"x":1,"x":2}',
            b'{"x":NaN}',
            b'{"x":1e309}',
            b'{"x":"\\ud800"}',
            b'{"\\udfff":0}',
            b'{"x":' + b"9" * (package.MAX_JSON_INTEGER_DIGITS + 1) + b"}",
        )
        claim_validator = load_current_claim_validator(package)
        for raw in malformed:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
                    package.strict_json_document(raw, "fixture")
                with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
                    package.assert_release_claims(
                        "request_v2.json", raw, claim_validator
                    )
                expected = {
                    package.RECEIPT_NAME: hashlib.sha256(b"receipt").hexdigest(),
                    package.WITNESS_MANIFEST_NAME: hashlib.sha256(raw).hexdigest(),
                }
                with self.assertRaisesRegex(RuntimeError, "manifest"):
                    package.validate_committed_baseline(
                        b"receipt", b"witness", {}, expected, raw
                    )

    def test_new_review_clearance_binds_a_reviewed_commit(self):
        package = load_packager()
        review_bytes = b"completed independent review\n"
        complete = {
            "schema": "jackal-spacecraft-independent-review-clearance-v175",
            "status": "complete",
            "reviewed_commit": "a" * 40,
            "completed_pass": 1,
            "resolved_findings": 0,
            "invalid_findings": 0,
            "unresolved_release_blocking": 0,
            "review_sha256": hashlib.sha256(review_bytes).hexdigest(),
        }
        package.validate_review_clearance(complete, "a" * 40, review_bytes)
        with self.assertRaisesRegex(RuntimeError, "reviewed commit"):
            package.validate_review_clearance(complete, "b" * 40, review_bytes)
        with self.assertRaisesRegex(RuntimeError, "review report digest"):
            package.validate_review_clearance(complete, "a" * 40, b"changed")
        for key, value in (
            ("status", "pending"),
            ("reviewed_commit", None),
            ("unresolved_release_blocking", 1),
        ):
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "clearance incomplete"):
                package.validate_review_clearance(
                    {**complete, key: value}, "a" * 40, review_bytes
                )
        for key in (
            "completed_pass",
            "resolved_findings",
            "invalid_findings",
            "unresolved_release_blocking",
        ):
            with self.subTest(boolean_field=key), self.assertRaisesRegex(
                RuntimeError, "clearance incomplete"
            ):
                package.validate_review_clearance(
                    {**complete, key: False}, "a" * 40, review_bytes
                )

    def test_review_report_must_be_complete_and_bind_source_and_commit(self):
        package = load_packager()
        commit = "a" * 40
        source_sha = "b" * 64
        clearance = {
            "completed_pass": 2,
            "resolved_findings": 3,
            "invalid_findings": 1,
            "unresolved_release_blocking": 0,
        }
        complete = (
            "# JACKAL v1.7.5 spacecraft-burn internal independent review\n"
            "\n"
            "Review schema: jackal-spacecraft-independent-review-v175\n"
            "Status: complete\n"
            f"Reviewed commit: `{commit}`\n"
            f"Producer source SHA-256: `{source_sha}`\n"
            "Completed review passes: 2\n"
            "Resolved findings: 3\n"
            "Invalid findings: 1\n"
            "Unresolved release-blocking findings: 0\n"
            "Review class: internal independent code review, not external peer review\n"
            "\n"
            "## Review scope\n"
            "The complete release package and every bound source were reviewed.\n"
            "\n"
            "## Findings and dispositions\n"
            "All enumerated findings were checked against the reviewed bytes.\n"
            "Disposition: R-001 | status: resolved | producer interval issue corrected and retested.\n"
            "Disposition: R-002 | status: resolved | package binding issue corrected and retested.\n"
            "Disposition: R-003 | status: resolved | mutation replay issue corrected and retested.\n"
            "Disposition: I-001 | status: invalid | reported concern disproved by exact source evidence.\n"
            "\n"
            "## Full-file Picard/source review\n"
            "The complete certify.py Picard implementation and refusal paths were reviewed.\n"
            "\n"
            "## Lean correspondence\n"
            "The Lean checker, theorem, interval, and source correspondence were reviewed.\n"
            "\n"
            "## Final zero-finding pass\n"
            "The final reviewed bytes were checked after all dispositions.\n"
            "Final pass result: pass 2 completed with zero new findings.\n"
        ).encode()
        package.validate_review_report(complete, commit, source_sha, clearance)
        wrong_final_pass = complete.replace(
            b"Final pass result: pass 2 completed with zero new findings.",
            b"Final pass result: pass 1 completed with zero new findings.",
        )
        with self.assertRaisesRegex(RuntimeError, "review report"):
            package.validate_review_report(
                wrong_final_pass, commit, source_sha, clearance
            )
        alternate_final_marker = complete.replace(
            b"Final pass result: pass 2 completed with zero new findings.",
            b"Final pass result: PASS 2 completed with zero new findings.",
        )
        with self.assertRaisesRegex(RuntimeError, "review report"):
            package.validate_review_report(
                alternate_final_marker, commit, source_sha, clearance
            )
        disposition_mismatch = complete.replace(
            b"Disposition: I-001 | status: invalid | reported concern disproved by exact source evidence.\n",
            b"",
        )
        with self.assertRaisesRegex(RuntimeError, "review report"):
            package.validate_review_report(
                disposition_mismatch, commit, source_sha, clearance
            )
        duplicate_disposition = complete.replace(b"R-002", b"R-001")
        with self.assertRaisesRegex(RuntimeError, "review report"):
            package.validate_review_report(
                duplicate_disposition, commit, source_sha, clearance
            )

        zero_clearance = {
            **clearance,
            "resolved_findings": 0,
            "invalid_findings": 0,
        }
        zero_findings = complete.replace(
            b"Resolved findings: 3\n", b"Resolved findings: 0\n"
        ).replace(
            b"Invalid findings: 1\n", b"Invalid findings: 0\n"
        )
        start = zero_findings.index(b"Disposition:")
        end = zero_findings.index(b"\n\n## Full-file", start)
        zero_findings = (
            zero_findings[:start]
            + b"No findings requiring disposition."
            + zero_findings[end:]
        )
        package.validate_review_report(
            zero_findings, commit, source_sha, zero_clearance
        )
        header_only = complete.split(b"## Review scope\n", 1)[0]
        with self.assertRaisesRegex(RuntimeError, "review report"):
            package.validate_review_report(
                header_only, commit, source_sha, clearance
            )
        for mutation in (
            complete.replace(b"Status: complete", b"Status: pending"),
            complete.replace(commit.encode(), ("c" * 40).encode()),
            complete.replace(source_sha.encode(), ("d" * 64).encode()),
            complete.replace(b"Completed review passes: 2", b"Completed review passes: 1"),
        ):
            with self.assertRaisesRegex(RuntimeError, "review report"):
                package.validate_review_report(mutation, commit, source_sha, clearance)

        contradictory = (
            b"Status: incomplete\n"
            b"Actual unresolved release-blocking findings: 7\n"
            b"Quoted template follows:\n"
            + complete
        )
        with self.assertRaisesRegex(RuntimeError, "review report"):
            package.validate_review_report(
                contradictory, commit, source_sha, clearance
            )

        duplicate = complete + complete.split(b"\n", 2)[2]
        with self.assertRaisesRegex(RuntimeError, "review report"):
            package.validate_review_report(duplicate, commit, source_sha, clearance)

    def test_reviewed_tree_allows_only_review_administration_changes(self):
        package = load_packager()
        self.assertEqual(
            package.REVIEW_ADMIN_PATHS,
            (
                package.REVIEW_LOGICAL_PATH,
                package.REVIEW_CLEARANCE_LOGICAL_PATH,
            ),
        )
        package.validate_reviewed_tree_changes(package.REVIEW_ADMIN_PATHS)
        with self.assertRaisesRegex(RuntimeError, "reviewed source tree"):
            package.validate_reviewed_tree_changes(
                [*package.REVIEW_ADMIN_PATHS, "spacecraft_burn_cert/certify.py"]
            )
        with self.assertRaisesRegex(RuntimeError, "reviewed source tree"):
            package.validate_reviewed_tree_changes([
                "docs/superpowers/plans/2026-08-24-spacecraft-burn-formal-certification-v2.md"
            ])

    def test_git_release_binding_rejects_nonexistent_commit_objects(self):
        package = load_packager()
        with self.assertRaisesRegex(RuntimeError, "release commit"):
            package.validate_git_release_binding("a" * 40, "b" * 40)

    def test_machine_readable_review_clearance_is_a_release_asset(self):
        package = load_packager()
        self.assertEqual(
            package.REVIEW_CLEARANCE_NAME,
            "spacecraft_burn_review_clearance_v175.json",
        )
        self.assertEqual(
            package.JSON_LOGICAL_PATHS[package.REVIEW_CLEARANCE_NAME],
            Path("release/evidence/spacecraft_burn_review_clearance_v175.json"),
        )

    def test_post_binding_tracked_input_mutation_refuses_before_output(self):
        package = load_packager()
        commit = "a" * 40
        reviewed_commit = "b" * 40
        committed = b"release-commit bytes\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracked = root / "tracked.txt"
            tracked.write_bytes(committed)
            output = root / "release-assets"

            def mutate_after_snapshot(_snapshot):
                tracked.write_bytes(b"post-binding mutation\n")

            with (
                mock.patch.object(package, "ROOT", root),
                mock.patch.object(
                    package, "tracked_input_paths", return_value=("tracked.txt",)
                ),
                mock.patch.object(package, "validate_git_release_binding"),
                mock.patch.object(package, "validate_git_object_integrity"),
                mock.patch.object(
                    package, "git_show_bytes", return_value=committed
                ),
                mock.patch.object(
                    package,
                    "_after_tracked_input_snapshot",
                    side_effect=mutate_after_snapshot,
                ),
            ):
                snapshot = package.validated_release_snapshot(
                    commit, reviewed_commit
                )
                with self.assertRaisesRegex(RuntimeError, "changed after snapshot"):
                    package.write_release_assets(
                        output,
                        {"asset.bin": b"asset"},
                        b"digest  asset.bin\n",
                        commit,
                        snapshot,
                    )
            self.assertFalse(output.exists())

    def test_post_binding_aba_restoration_cannot_substitute_mutant_bytes(self):
        package = load_packager()
        commit = "a" * 40
        reviewed_commit = "b" * 40
        committed = b"A: release-commit bytes\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracked = root / "tracked.txt"
            tracked.write_bytes(committed)
            output = root / "release-assets"

            def aba_after_snapshot(_snapshot):
                tracked.write_bytes(b"B: transient mutant bytes\n")
                tracked.write_bytes(committed)

            with (
                mock.patch.object(package, "ROOT", root),
                mock.patch.object(
                    package, "tracked_input_paths", return_value=("tracked.txt",)
                ),
                mock.patch.object(package, "validate_git_release_binding"),
                mock.patch.object(package, "validate_git_object_integrity"),
                mock.patch.object(
                    package, "git_show_bytes", return_value=committed
                ),
                mock.patch.object(
                    package,
                    "_after_tracked_input_snapshot",
                    side_effect=aba_after_snapshot,
                ),
            ):
                snapshot = package.validated_release_snapshot(
                    commit, reviewed_commit
                )
                package.write_release_assets(
                    output,
                    {"asset.bin": snapshot["tracked.txt"]},
                    b"digest  asset.bin\n",
                    commit,
                    snapshot,
                )
            self.assertEqual((output / "asset.bin").read_bytes(), committed)

    def test_release_asset_set_is_not_partially_published_on_write_failure(self):
        package = load_packager()
        commit = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "release-assets"
            calls = 0
            real_atomic_write = package.atomic_write

            def fail_second_write(path, data, mode=0o644):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated release-set write failure")
                return real_atomic_write(path, data, mode)

            with (
                mock.patch.object(package, "validate_tracked_inputs_unchanged"),
                mock.patch.object(
                    package, "atomic_write", side_effect=fail_second_write
                ),
            ):
                with self.assertRaisesRegex(OSError, "release-set write failure"):
                    package.write_release_assets(
                        output,
                        {"first.bin": b"first", "second.bin": b"second"},
                        b"digest  first.bin\n",
                        commit,
                        {"tracked.txt": b"tracked"},
                    )
            self.assertFalse(output.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_release_output_rejects_a_dangling_symlink(self):
        package = load_packager()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "release-assets"
            missing_target = root / "missing-target"
            output.symlink_to(missing_target, target_is_directory=True)
            with mock.patch.object(
                package, "validate_tracked_inputs_unchanged"
            ):
                with self.assertRaisesRegex(FileExistsError, "already exists"):
                    package.write_release_assets(
                        output,
                        {"asset.bin": b"asset"},
                        b"digest  asset.bin\n",
                        "a" * 40,
                        {"tracked.txt": b"tracked"},
                    )
            self.assertTrue(output.is_symlink())
            self.assertEqual(os.readlink(output), str(missing_target))
            self.assertEqual(
                [path.name for path in root.iterdir()], ["release-assets"]
            )

    def test_cli_preserves_dangling_output_symlink_for_refusal(self):
        package = load_packager()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging = root / "staging"
            staging.mkdir()
            output = root / "release-assets"
            missing_target = root / "missing-target"
            output.symlink_to(missing_target, target_is_directory=True)

            def minimal_build(_staging, lexical_output, commit, _reviewed):
                package.write_release_assets(
                    lexical_output,
                    {"asset.bin": b"asset"},
                    b"digest  asset.bin\n",
                    commit,
                    {"tracked.txt": b"tracked"},
                )
                return {}

            with (
                mock.patch.object(package, "validate_publication_startup"),
                mock.patch.object(package, "build", side_effect=minimal_build),
                mock.patch.object(
                    package, "validate_tracked_inputs_unchanged"
                ),
            ):
                with self.assertRaisesRegex(FileExistsError, "already exists"):
                    package.main(
                        [
                            "--staging-dir",
                            str(staging),
                            "--output-dir",
                            str(output),
                            "--merge-commit",
                            "a" * 40,
                            "--reviewed-commit",
                            "b" * 40,
                        ]
                    )
            self.assertTrue(output.is_symlink())
            self.assertFalse(missing_target.exists())

    def test_final_release_rename_is_exclusive_against_a_racing_destination(self):
        package = load_packager()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "release-assets"
            real_publish = package.rename_directory_exclusive

            def install_racing_destination(source, destination):
                destination.mkdir()
                (destination / "competitor.txt").write_text("competitor\n")
                return real_publish(source, destination)

            with (
                mock.patch.object(
                    package, "validate_tracked_inputs_unchanged"
                ),
                mock.patch.object(
                    package,
                    "rename_directory_exclusive",
                    side_effect=install_racing_destination,
                ),
            ):
                with self.assertRaisesRegex(FileExistsError, "already exists"):
                    package.write_release_assets(
                        output,
                        {"asset.bin": b"asset"},
                        b"digest  asset.bin\n",
                        "a" * 40,
                        {"tracked.txt": b"tracked"},
                    )
            self.assertEqual(
                (output / "competitor.txt").read_text(), "competitor\n"
            )
            self.assertFalse((output / "asset.bin").exists())
            self.assertEqual(
                [path.name for path in root.iterdir()], ["release-assets"]
            )

    def test_release_publication_fsyncs_directories_around_final_rename(self):
        package = load_packager()
        commit = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "release-assets"
            events = []
            real_atomic_write = package.atomic_write
            real_publish = package.rename_directory_exclusive

            def recorded_write(path, data, mode=0o644):
                events.append(("write", Path(path).name))
                return real_atomic_write(path, data, mode)

            def recorded_fsync(path):
                events.append(("fsync", Path(path)))

            def recorded_publish(source, destination):
                events.append(("rename", Path(source), Path(destination)))
                return real_publish(source, destination)

            with (
                mock.patch.object(package, "validate_tracked_inputs_unchanged"),
                mock.patch.object(
                    package, "atomic_write", side_effect=recorded_write
                ),
                mock.patch.object(
                    package, "fsync_directory", side_effect=recorded_fsync
                ),
                mock.patch.object(
                    package,
                    "rename_directory_exclusive",
                    side_effect=recorded_publish,
                ),
            ):
                package.write_release_assets(
                    output,
                    {"asset.bin": b"asset"},
                    b"digest  asset.bin\n",
                    commit,
                    {"tracked.txt": b"tracked"},
                )

            rename_index = next(
                index for index, event in enumerate(events) if event[0] == "rename"
            )
            temporary = events[rename_index][1]
            self.assertEqual(
                events,
                [
                    ("write", "asset.bin"),
                    ("fsync", temporary),
                    ("write", "SHA256SUMS"),
                    ("fsync", temporary),
                    ("fsync", temporary),
                    ("fsync", root),
                    ("rename", temporary, output),
                    ("fsync", root),
                ],
            )
            self.assertTrue(output.is_dir())

    def test_auxiliary_evidence_is_semantically_cross_bound(self):
        package = load_packager()
        evidence = ROOT / "spacecraft_burn_cert/evidence"
        receipt_bytes = (evidence / package.RECEIPT_NAME).read_bytes()
        receipt = json.loads(receipt_bytes)
        documents = {
            name: json.loads((evidence / name).read_text())
            for name in package.AUXILIARY_EVIDENCE_NAMES
        }
        independent = documents["independent_verification_v2.json"]
        instrument = documents["instrument_validation_v2.json"]
        mutation = documents["mutation_aba_v2.json"]
        source_mutants = {
            row["mutation"]: row for row in mutation["mutations"]
        }
        witness_records = {
            row["mutation"]: row
            for row in mutation["witness_mutations"]
        }
        bindings = {
            "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "witness_sha256": receipt["formal_checker"]["witness_sha256"],
            "checker_sha256": receipt["formal_checker"]["checker_sha256"],
            "proof_identity_file_sha256": receipt["formal_checker"]
            ["proof_identity_file_sha256"],
            "proof_identity_digest_sha256": receipt["formal_checker"]
            ["proof_identity_digest_sha256"],
            "request_digest": receipt["formal_checker"]["request_digest"],
            "model_id": receipt["formal_checker"]["model_id"],
            "epoch": receipt["formal_checker"]["epoch"],
            "nonce": receipt["formal_checker"]["nonce"],
            "source_sha256": receipt["source_sha256"],
        }

        package.validate_auxiliary_documents(
            documents,
            receipt,
            bindings,
            expected_independent=independent,
            expected_instrument=instrument,
            expected_source_mutants=source_mutants,
            expected_witness_records=witness_records,
        )

        mutations = (
            (
                "independent_verification_v2.json",
                ("binding", "receipt_sha256"),
                "0" * 64,
            ),
            (
                "instrument_validation_v2.json",
                ("baseline_receipt_sha256",),
                "0" * 64,
            ),
            (
                "mutation_aba_v2.json",
                ("baseline_source_sha256",),
                "0" * 64,
            ),
            (
                "mutation_aba_v2.json",
                ("witness_mutations", 0, "original_sha256"),
                "0" * 64,
            ),
            (
                "mutation_aba_v2.json",
                ("mutations", 0, "mutant_test_output_sha256"),
                "0" * 64,
            ),
            (
                "mutation_aba_v2.json",
                ("baseline_verifier_before_process", "returncode"),
                False,
            ),
            (
                "mutation_aba_v2.json",
                ("baseline_verifier_after_process", "output_sha256"),
                "0" * 64,
            ),
            (
                "mutation_aba_v2.json",
                ("witness_mutations", 0, "checker_returncode"),
                True,
            ),
        )
        for name, path, replacement in mutations:
            with self.subTest(name=name, path=path):
                changed = json.loads(json.dumps(documents))
                target = changed[name]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = replacement
                with self.assertRaisesRegex(RuntimeError, "auxiliary evidence"):
                    package.validate_auxiliary_documents(
                        changed,
                        receipt,
                        bindings,
                        expected_independent=independent,
                        expected_instrument=instrument,
                        expected_source_mutants=source_mutants,
                        expected_witness_records=witness_records,
                    )


if __name__ == "__main__":
    unittest.main()
