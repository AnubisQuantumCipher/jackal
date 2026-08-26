from __future__ import annotations

import ast
import importlib.util
import hashlib
import copy
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "verify_receipt.py"
CERTIFIER = ROOT / "certify.py"
BASELINE = ROOT / "evidence" / "legacy-v1" / "baseline_receipt.json"
PROOF_IDENTITY = ROOT.parent / "release" / "evidence" / "spacecraft_burn_proof_identity_v1.json"
CHECKER = ROOT.parent / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_spacecraft_burn_check"
REQUEST_DIGEST = "03bcad618ad60114007c74a384eb8c9432e3755b817e74bd5bdc9bd1ba6df3e7"
MODEL_ID = "jackal-spacecraft-finite-burn-ode-v2"
EPOCH = "v1.7.5"
NONCE = "verifier-mutation-test"
QUALIFIER = (
    "under the stated finite-burn ODE model, supplied input bounds, "
    "and machine-checked interval-certificate assumptions"
)
PICARD_PRODUCER_NONCLAIM = (
    "The Python Picard witness generator and its source are not formally verified. "
    "They are outside the mathematical soundness base because the pinned Lean "
    "checker independently checks every accepted tube, but remain trusted for "
    "termination, witness search/completeness, and reproducible generation. A "
    "producer defect may cause refusal, nontermination, or failure to find a "
    "witness, but cannot yield formal ACCEPT absent a defect in the pinned Lean "
    "checker or outer verification gate."
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_verifier(testcase: unittest.TestCase):
    if not VERIFIER.is_file():
        testcase.fail("verify_receipt.py is missing")
    spec = importlib.util.spec_from_file_location("spacecraft_verifier", VERIFIER)
    if spec is None or spec.loader is None:
        testcase.fail("verify_receipt.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IndependentVerifierTests(unittest.TestCase):
    def test_missing_producer_source_root_refuses_without_traceback(self):
        verifier = load_verifier(self)
        with tempfile.TemporaryDirectory() as directory:
            missing_source = Path(directory) / "missing-root" / "producer" / "certify.py"
            result = verifier.verify_receipt(
                ROOT / "evidence/baseline_receipt_v2.json",
                missing_source,
                request_path=ROOT / "request_v2.json",
            )

        self.assertEqual(
            result,
            {"status": "REFUSED", "reasons": ["invalid-producer-source"]},
        )

    def test_malformed_producer_source_roots_refuse_without_traceback(self):
        verifier = load_verifier(self)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "producer" / "certify.py"
            with mock.patch.object(
                verifier.Path,
                "resolve",
                side_effect=RuntimeError("Symlink loop from publication interpreter"),
            ):
                loop_result = verifier.verify_receipt(
                    ROOT / "evidence/baseline_receipt_v2.json",
                    source,
                    request_path=ROOT / "request_v2.json",
                )
            nul_result = verifier.verify_receipt(
                ROOT / "evidence/baseline_receipt_v2.json",
                "producer\0/certify.py",
                request_path=ROOT / "request_v2.json",
            )

        self.assertEqual(
            loop_result,
            {"status": "REFUSED", "reasons": ["invalid-producer-source"]},
        )
        self.assertEqual(
            nul_result,
            {"status": "REFUSED", "reasons": ["invalid-producer-source"]},
        )

    def test_detached_proof_identity_resolves_exact_sources_from_explicit_root(self):
        verifier = load_verifier(self)
        identity = json.loads(PROOF_IDENTITY.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="detached-proof-identity-") as directory:
            detached = Path(directory) / PROOF_IDENTITY.name
            detached.write_bytes(PROOF_IDENTITY.read_bytes())
            reasons: list[str] = []
            observed = verifier.verify_identity_file(
                detached,
                sha(PROOF_IDENTITY),
                identity["identity_digest_sha256"],
                identity["checker"]["sha256"],
                REQUEST_DIGEST,
                MODEL_ID,
                EPOCH,
                reasons,
                checker_size=identity["checker"]["bytes"],
                source_root=ROOT.parent,
            )

        self.assertEqual(observed, sha(PROOF_IDENTITY))
        self.assertEqual(reasons, [])

    def test_explicit_source_root_cannot_borrow_identity_sibling_sources(self):
        verifier = load_verifier(self)
        identity = json.loads(PROOF_IDENTITY.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="empty-proof-source-root-") as directory:
            reasons: list[str] = []
            verifier.verify_identity_file(
                PROOF_IDENTITY,
                sha(PROOF_IDENTITY),
                identity["identity_digest_sha256"],
                identity["checker"]["sha256"],
                REQUEST_DIGEST,
                MODEL_ID,
                EPOCH,
                reasons,
                checker_size=identity["checker"]["bytes"],
                source_root=Path(directory),
            )

        self.assertIn("proof-identity-source-closure-mismatch", reasons)
        self.assertIn("proof-identity-generator-mismatch", reasons)
        self.assertIn("proof-identity-toolchain-mismatch", reasons)

    def test_identity_bound_reads_refuse_intermediate_symlinks(self):
        verifier = load_verifier(self)
        identity = json.loads(PROOF_IDENTITY.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="identity-symlink-root-") as directory:
            temporary = Path(directory)
            source_root = temporary / "source"
            outside = temporary / "outside"
            source_root.mkdir()
            generator = outside / "release" / "tools" / "gaussian_proof_identity.py"
            generator.parent.mkdir(parents=True)
            generator.write_bytes(
                (ROOT.parent / "release/tools/gaussian_proof_identity.py").read_bytes()
            )
            (source_root / "release").symlink_to(
                outside / "release", target_is_directory=True
            )
            lean_source = outside / "proofs" / "JackalIv" / "Bound.lean"
            lean_source.parent.mkdir(parents=True)
            lean_source.write_text("theorem bound : True := trivial\n", encoding="utf-8")
            (source_root / "proofs").mkdir()
            (source_root / "proofs" / "JackalIv").symlink_to(
                outside / "proofs" / "JackalIv", target_is_directory=True
            )

            self.assertIsNone(
                verifier.resolve_identity_bound_path(
                    PROOF_IDENTITY,
                    "release/tools/gaussian_proof_identity.py",
                    source_root,
                )
            )
            self.assertIsNone(
                verifier.resolve_identity_bound_path(
                    PROOF_IDENTITY,
                    "proofs/lean/JackalIv/Bound.lean",
                    source_root,
                )
            )
            reasons: list[str] = []
            verifier.verify_identity_file(
                PROOF_IDENTITY,
                sha(PROOF_IDENTITY),
                identity["identity_digest_sha256"],
                identity["checker"]["sha256"],
                REQUEST_DIGEST,
                MODEL_ID,
                EPOCH,
                reasons,
                checker_size=identity["checker"]["bytes"],
                source_root=source_root,
            )

        self.assertIn("proof-identity-source-closure-mismatch", reasons)
        self.assertIn("proof-identity-generator-mismatch", reasons)
        self.assertIn("proof-identity-toolchain-mismatch", reasons)

    def test_identity_bound_reads_accept_complete_packaged_layout(self):
        verifier = load_verifier(self)
        identity = json.loads(PROOF_IDENTITY.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="identity-packaged-root-") as directory:
            source_root = Path(directory)
            recorded_paths = [
                row["path"] for row in identity["source_closure"]["files"]
            ]
            recorded_paths.extend(
                row["path"] for row in identity["toolchain"]["configuration_files"]
            )
            for recorded in recorded_paths:
                relative = Path(recorded)
                packaged = source_root / "proofs" / Path(*relative.parts[2:])
                packaged.parent.mkdir(parents=True, exist_ok=True)
                packaged.write_bytes((ROOT.parent / relative).read_bytes())
            for row in identity["generator"]["files"]:
                relative = Path(row["path"])
                destination = source_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT.parent / relative).read_bytes())

            reasons: list[str] = []
            verifier.verify_identity_file(
                PROOF_IDENTITY,
                sha(PROOF_IDENTITY),
                identity["identity_digest_sha256"],
                identity["checker"]["sha256"],
                REQUEST_DIGEST,
                MODEL_ID,
                EPOCH,
                reasons,
                checker_size=identity["checker"]["bytes"],
                source_root=source_root,
            )

        self.assertEqual(reasons, [])

    def test_identity_bound_source_root_is_held_open_against_replacement(self):
        verifier = load_verifier(self)
        with tempfile.TemporaryDirectory(prefix="identity-open-root-") as directory:
            temporary = Path(directory)
            source_root = temporary / "source"
            original = b"original exact source bytes\n"
            bound = source_root / "release" / "tools" / "bound.py"
            bound.parent.mkdir(parents=True)
            bound.write_bytes(original)
            with verifier.IdentityBoundSource(PROOF_IDENTITY, source_root) as source:
                moved = temporary / "moved-source"
                source_root.rename(moved)
                replacement = source_root / "release" / "tools" / "bound.py"
                replacement.parent.mkdir(parents=True)
                replacement.write_bytes(b"replacement bytes\n")
                observed = source.read("release/tools/bound.py", 1024)

        self.assertEqual(observed, original)

    def test_cli_refuses_symlink_hardlink_and_resolved_parent_output_aliases(self):
        verifier = load_verifier(self)

        def arguments(root: Path, receipt: Path, output: Path) -> list[str]:
            source = root / "source.py"
            request = root / "request.json"
            witness = root / "witness.cert"
            checker = root / "checker"
            identity = root / "identity.json"
            for path in (source, request, witness, checker, identity):
                path.write_bytes(path.name.encode("ascii"))
            return [
                str(receipt),
                "--source", str(source),
                "--request", str(request),
                "--witness", str(witness),
                "--checker", str(checker),
                "--proof-identity", str(identity),
                "--expected-receipt-sha256", "a" * 64,
                "--expected-proof-file-sha256", "b" * 64,
                "--expected-proof-identity-sha256", "c" * 64,
                "--expected-request-digest", "d" * 64,
                "--expected-model-id", MODEL_ID,
                "--expected-epoch", EPOCH,
                "--nonce", NONCE,
                "--output", str(output),
            ]

        for case in ("symlink", "dangling-symlink", "hardlink", "resolved-parent"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                real = root / "real"
                real.mkdir()
                receipt = real / "receipt.json"
                original = b"authoritative receipt\n"
                receipt.write_bytes(original)
                if case == "symlink":
                    output = root / "output.json"
                    output.symlink_to(receipt)
                elif case == "dangling-symlink":
                    output = root / "output.json"
                    output.symlink_to(root / "missing.json")
                elif case == "hardlink":
                    output = root / "output.json"
                    os.link(receipt, output)
                else:
                    alias = root / "alias"
                    alias.symlink_to(real, target_is_directory=True)
                    output = alias / receipt.name
                with mock.patch.object(
                    verifier,
                    "verify_receipt",
                    return_value={"status": "ACCEPT", "reasons": []},
                ) as verify:
                    with self.assertRaises(SystemExit):
                        verifier.main(arguments(root, receipt, output))
                verify.assert_not_called()
                self.assertEqual(receipt.read_bytes(), original)

    def test_bounded_open_once_snapshot_refuses_symlink_fifo_and_oversize(self):
        verifier = load_verifier(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regular = root / "regular"
            regular.write_bytes(b"exact")
            self.assertEqual(verifier.read_regular_snapshot(regular, 5), b"exact")

            link = root / "link"
            link.symlink_to(regular)
            fifo = root / "fifo"
            os.mkfifo(fifo)
            oversized = root / "oversized"
            with oversized.open("wb") as stream:
                stream.truncate(9)
            for path in (link, fifo, oversized):
                with self.subTest(path=path.name), self.assertRaises((OSError, ValueError)):
                    verifier.read_regular_snapshot(path, 8)

    def test_atomic_verifier_output_completes_short_writes_and_cleans_failure(self):
        verifier = load_verifier(self)
        payload = b"verification output" * 64
        real_write = os.write

        def short_write(descriptor, data):
            return real_write(descriptor, data[:max(1, len(data) // 3)])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "verification.json"
            with mock.patch.object(verifier.os, "write", side_effect=short_write):
                verifier.write_output_atomic(destination, payload)
            self.assertEqual(destination.read_bytes(), payload)

            failed = root / "failed.json"
            with (
                mock.patch.object(
                    verifier.os, "write", side_effect=OSError("write failed")
                ),
                self.assertRaisesRegex(OSError, "write failed"),
            ):
                verifier.write_output_atomic(failed, payload)
            self.assertFalse(failed.exists())
            self.assertEqual(list(root.glob(".failed.json.tmp-*")), [])

    def test_checker_execution_uses_private_byte_snapshots(self):
        verifier = load_verifier(self)
        checker_bytes = b"#!/bin/sh\nexit 0\n"
        witness_bytes = b"bound witness\n"
        observed: dict[str, object] = {}

        def fake_run(command, **kwargs):
            checker_snapshot, witness_snapshot = map(Path, command[:2])
            observed["checker"] = checker_snapshot.read_bytes()
            observed["witness"] = witness_snapshot.read_bytes()
            observed["private"] = checker_snapshot.parent == witness_snapshot.parent
            return subprocess.CompletedProcess(command, 0, b"ACCEPT\n", b"")

        with mock.patch.object(verifier, "run_bounded_process", side_effect=fake_run):
            completed = verifier.run_checker_snapshot(
                checker_bytes, witness_bytes, "request", "model", "epoch", 10
            )
        self.assertEqual(completed.stdout, "ACCEPT\n")
        self.assertEqual(observed, {
            "checker": checker_bytes,
            "witness": witness_bytes,
            "private": True,
        })

    def test_checker_capture_is_hard_bounded_and_ascii_only(self):
        verifier = load_verifier(self)
        malformed = (
            (
                b"#!/bin/sh\n/usr/bin/printf '\\377'\n",
                "checker-output-not-ascii",
            ),
            (
                b"#!/bin/sh\n/usr/bin/head -c 8192 /dev/zero\n",
                "checker-output-limit",
            ),
        )
        for checker, reason in malformed:
            with self.subTest(reason=reason), self.assertRaisesRegex(
                verifier.CheckerExecutionError, reason
            ):
                verifier.run_checker_snapshot(
                    checker, b"witness", "request", "model", "epoch", 10
                )

    def test_identity_digest_uses_the_already_parsed_bytes(self):
        verifier = load_verifier(self)
        identity = json.loads(PROOF_IDENTITY.read_text(encoding="utf-8"))
        reasons: list[str] = []
        with mock.patch.object(
            verifier, "sha256_file", side_effect=AssertionError("unexpected reread")
        ):
            verifier.verify_identity_file(
                PROOF_IDENTITY,
                sha(PROOF_IDENTITY),
                identity["identity_digest_sha256"],
                identity["checker"]["sha256"],
                REQUEST_DIGEST,
                MODEL_ID,
                EPOCH,
                reasons,
            )
        self.assertEqual(reasons, [])

    def test_identity_refuses_a_substituted_delegated_generator_engine(self):
        verifier = load_verifier(self)
        identity = json.loads(PROOF_IDENTITY.read_text(encoding="utf-8"))
        real_read = verifier.read_identity_bound_snapshot
        with tempfile.TemporaryDirectory() as directory:
            substitute = Path(directory) / "gaussian_proof_identity.py"
            substitute.write_text("# substituted identity engine\n", encoding="utf-8")

            def read(
                identity_path,
                recorded,
                maximum_bytes,
                source_root=None,
                *,
                source=None,
            ):
                if recorded == "release/tools/gaussian_proof_identity.py":
                    return substitute.read_bytes()
                return real_read(
                    identity_path,
                    recorded,
                    maximum_bytes,
                    source_root,
                    source=source,
                )

            reasons: list[str] = []
            with mock.patch.object(
                verifier, "read_identity_bound_snapshot", side_effect=read
            ):
                verifier.verify_identity_file(
                    PROOF_IDENTITY,
                    sha(PROOF_IDENTITY),
                    identity["identity_digest_sha256"],
                    identity["checker"]["sha256"],
                    REQUEST_DIGEST,
                    MODEL_ID,
                    EPOCH,
                    reasons,
                )
        self.assertIn("proof-identity-generator-mismatch", reasons)

    def test_identity_path_search_is_compatible_with_system_python(self):
        verifier = load_verifier(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity = root / "release" / "evidence" / "identity.json"
            identity.parent.mkdir(parents=True)
            identity.write_bytes(b"{}\n")
            source = root / "proofs" / "lean" / "JackalIv" / "Bound.lean"
            source.parent.mkdir(parents=True)
            source.write_text("theorem bound : True := trivial\n", encoding="utf-8")

            self.assertEqual(
                verifier.resolve_identity_bound_path(
                    identity, "proofs/lean/JackalIv/Bound.lean"
                ),
                source.resolve(),
            )
            self.assertTrue(
                verifier.repository_local_lean_module_exists(
                    identity, "JackalIv.Bound"
                )
            )

    def test_platform_launcher_roles_refuse_relabelled_system_paths(self):
        verifier = load_verifier(self)
        rows = [
            {
                "bytes": 1,
                "invocation_path": "/usr/bin/python3",
                "invocation_symlink_target": None,
                "resolved_path": "/usr/bin/python3",
                "role": "python-launcher",
                "sha256": "1" * 64,
            },
            {
                "bytes": 1,
                "invocation_path": "/Applications/Xcode/Python3",
                "invocation_symlink_target": None,
                "resolved_path": "/Applications/Xcode/Python3",
                "role": "python-interpreter",
                "sha256": "2" * 64,
            },
            {
                "bytes": 1,
                "invocation_path": "/usr/bin/git",
                "invocation_symlink_target": None,
                "resolved_path": "/usr/bin/git",
                "role": "git-client",
                "sha256": "3" * 64,
            },
            {
                "bytes": 1,
                "invocation_path": "/usr/bin/sandbox-exec",
                "invocation_symlink_target": None,
                "resolved_path": "/usr/bin/sandbox-exec",
                "role": "sandbox-launcher",
                "sha256": "4" * 64,
            },
        ]
        self.assertTrue(verifier.trusted_platform_launchers_valid(rows))
        for index, field, substitute in (
            (0, "invocation_path", "/tmp/python3"),
            (2, "invocation_path", "/tmp/git"),
            (3, "invocation_path", "/tmp/sandbox-exec"),
            (0, "resolved_path", "/tmp/python3"),
            (2, "resolved_path", "/tmp/git"),
            (3, "resolved_path", "/tmp/sandbox-exec"),
            (0, "invocation_symlink_target", "python3-substitute"),
            (2, "invocation_symlink_target", "git-substitute"),
            (3, "invocation_symlink_target", "sandbox-substitute"),
        ):
            with self.subTest(role=rows[index]["role"], field=field):
                mutated = copy.deepcopy(rows)
                mutated[index][field] = substitute
                self.assertFalse(verifier.trusted_platform_launchers_valid(mutated))

    def test_redigested_identity_semantic_mutations_are_refused(self):
        verifier = load_verifier(self)
        original = json.loads(PROOF_IDENTITY.read_text(encoding="utf-8"))

        def reasons_for(path: Path, document: dict) -> list[str]:
            reasons: list[str] = []
            verifier.verify_identity_file(
                path,
                sha(path),
                document["identity_digest_sha256"],
                document["checker"]["sha256"],
                REQUEST_DIGEST,
                MODEL_ID,
                EPOCH,
                reasons,
            )
            return reasons

        self.assertEqual(reasons_for(PROOF_IDENTITY, original), [])

        def redigest(document: dict, *, attestation: bool = False) -> None:
            if attestation:
                build = document["build_attestation"]
                build_body = {
                    key: value
                    for key, value in build.items()
                    if key != "attestation_digest_sha256"
                }
                build["attestation_digest_sha256"] = hashlib.sha256(
                    verifier.canonical_json_bytes(build_body)
                ).hexdigest()
            body = {
                key: value
                for key, value in document.items()
                if key != "identity_digest_sha256"
            }
            document["identity_digest_sha256"] = hashlib.sha256(
                verifier.canonical_json_bytes(body)
            ).hexdigest()

        evidence_dir = ROOT.parent / "release" / "evidence"
        with tempfile.TemporaryDirectory(
            prefix="identity-semantic-mutation-", dir=evidence_dir
        ) as directory:
            mutation_root = Path(directory)

            theorem = copy.deepcopy(original)
            theorem["proof"]["theorems"][0]["theorem"] = "False.fabricated"
            redigest(theorem)
            theorem_path = mutation_root / "theorem.json"
            theorem_path.write_text(
                json.dumps(theorem, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.assertIn(
                "proof-identity-axiom-policy-mismatch",
                reasons_for(theorem_path, theorem),
            )

            for field, value in (
                ("sha256", "0" * 64),
                ("package_count", 0),
                ("package_names", []),
            ):
                with self.subTest(override_field=field):
                    override = copy.deepcopy(original)
                    override["build_attestation"]["build_environment"][
                        "dependency_path_overrides"
                    ][field] = value
                    redigest(override, attestation=True)
                    override_path = mutation_root / f"override-{field}.json"
                    override_path.write_text(
                        json.dumps(override, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    self.assertIn(
                        "proof-identity-build-attestation-mismatch",
                        reasons_for(override_path, override),
                    )

            bookkeeping = copy.deepcopy(original)
            bookkeeping["build_attestation"]["build_environment"][
                "lake_generated_bookkeeping"
            ]["files"][0]["sha256"] = "0" * 64
            redigest(bookkeeping, attestation=True)
            bookkeeping_path = mutation_root / "lake-bookkeeping.json"
            bookkeeping_path.write_text(
                json.dumps(bookkeeping, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.assertIn(
                "proof-identity-build-attestation-mismatch",
                reasons_for(bookkeeping_path, bookkeeping),
            )

            for role, field, substitute in (
                ("git-client", "invocation_path", "/tmp/git"),
                ("git-client", "resolved_path", "/tmp/git"),
                ("sandbox-launcher", "invocation_symlink_target", "substitute"),
            ):
                with self.subTest(launcher_role=role, field=field):
                    launcher = copy.deepcopy(original)
                    row = next(
                        item
                        for item in launcher["build_attestation"]["build_environment"][
                            "trusted_platform_launchers"
                        ]
                        if item["role"] == role
                    )
                    row[field] = substitute
                    redigest(launcher, attestation=True)
                    launcher_path = mutation_root / f"launcher-{role}.json"
                    launcher_path.write_text(
                        json.dumps(launcher, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    self.assertIn(
                        "proof-identity-build-attestation-mismatch",
                        reasons_for(launcher_path, launcher),
                    )

    def test_identity_semantics_refuses_nonstring_digest_fields(self):
        verifier = load_verifier(self)
        original = json.loads(PROOF_IDENTITY.read_text(encoding="utf-8"))
        mutations = (
            (
                "manifest-packages",
                ("toolchain", "manifest_packages"),
                "proof-identity-toolchain-mismatch",
            ),
            (
                "package-tree-sha1",
                ("toolchain", "verified_package_trees", 0, "tree_sha1"),
                "proof-identity-toolchain-mismatch",
            ),
            (
                "package-worktree-sha256",
                (
                    "toolchain",
                    "verified_package_trees",
                    0,
                    "verified_worktree_sha256",
                ),
                "proof-identity-toolchain-mismatch",
            ),
            (
                "dependency-overrides-sha256",
                (
                    "build_attestation",
                    "build_environment",
                    "dependency_path_overrides",
                    "sha256",
                ),
                "proof-identity-build-attestation-mismatch",
            ),
            (
                "lean-launcher-sha256",
                (
                    "build_attestation",
                    "build_environment",
                    "lean_launcher_binaries",
                    0,
                    "sha256",
                ),
                "proof-identity-build-attestation-mismatch",
            ),
            (
                "toolchain-tree-sha256",
                (
                    "build_attestation",
                    "build_environment",
                    "lean_toolchain_tree",
                    "aggregate_sha256",
                ),
                "proof-identity-build-attestation-mismatch",
            ),
            (
                "platform-launcher-sha256",
                (
                    "build_attestation",
                    "build_environment",
                    "trusted_platform_launchers",
                    0,
                    "sha256",
                ),
                "proof-identity-build-attestation-mismatch",
            ),
        )

        for label, path, expected_reason in mutations:
            with self.subTest(field=label):
                document = copy.deepcopy(original)
                target = document
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = None
                reasons: list[str] = []
                verifier.validate_identity_semantics(
                    document,
                    PROOF_IDENTITY,
                    checker_digest=document["checker"]["sha256"],
                    checker_size=document["checker"]["bytes"],
                    request_digest=REQUEST_DIGEST,
                    model_id=MODEL_ID,
                    epoch=EPOCH,
                    reasons=reasons,
                )
                self.assertIn(expected_reason, reasons)

    def test_source_literals_parse_caller_supplied_bytes(self):
        verifier = load_verifier(self)
        raw = b'THRUST_KM_SCALE_TEXT = "0.001"\nINTEGRATE_MASS = True\n'
        self.assertEqual(
            verifier.source_literals(raw, Path("producer.py")),
            {"THRUST_KM_SCALE_TEXT": "0.001", "INTEGRATE_MASS": True},
        )

    def test_source_hash_mismatch_refuses_before_contract_parser_runs(self):
        verifier = load_verifier(self)
        receipt = ROOT / "evidence" / "baseline_receipt_v2.json"
        request = ROOT / "request_v2.json"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "producer" / "certify.py"
            source.parent.mkdir()
            source.write_bytes(
                b'THRUST_KM_SCALE_TEXT = "wrong source must not be parsed"\n'
            )
            with (
                mock.patch.object(
                    verifier,
                    "verify_formal_binding",
                    return_value=([], {}),
                ),
                mock.patch.object(
                    verifier,
                    "source_literals",
                    side_effect=AssertionError(
                        "source contract parser ran before receipt-bound hash refusal"
                    ),
                ) as parser,
            ):
                result = verifier.verify_receipt(
                    receipt,
                    source,
                    request_path=request,
                    expected_request_digest=REQUEST_DIGEST,
                )

        self.assertEqual(
            result,
            {"status": "REFUSED", "reasons": ["source-hash-mismatch"]},
        )
        parser.assert_not_called()

    def test_source_contract_extraction_refuses_excessive_literal_graph(self):
        verifier = load_verifier(self)
        hostile = (
            b"THRUST_KM_SCALE_TEXT = ["
            + (b"0," * 100_000)
            + b"]\n"
        )
        self.assertLess(len(hostile), verifier.MAX_SOURCE_BYTES)
        with (
            mock.patch.object(
                ast,
                "parse",
                side_effect=AssertionError("whole-file AST parser reached"),
            ) as ast_parse,
            mock.patch.object(
                ast,
                "literal_eval",
                side_effect=AssertionError("literal graph materializer reached"),
            ) as literal_eval,
        ):
            with self.assertRaises(ValueError):
                verifier.source_literals(hostile, Path("hostile-producer.py"))
        ast_parse.assert_not_called()
        literal_eval.assert_not_called()

    def test_outer_source_closure_scan_rejects_all_axiom_declaration_forms(self):
        verifier = load_verifier(self)
        for declaration in (
            "axiom fabricated : False",
            "axioms fabricated : False",
            "private axiom fabricated : False",
            "protected axiom fabricated : False",
            "local axiom fabricated : False",
            "noncomputable axiom fabricated : False",
            "public axiom fabricated : False",
            "@[deprecated] axiom fabricated : False",
            "@[irreducible] private axioms fabricated : False",
        ):
            with self.subTest(declaration=declaration):
                code = verifier.lean_code_without_comments_or_strings(declaration)
                self.assertTrue(verifier.has_forbidden_lean_construct(code))
        for harmless in (
            "-- private axiom fabricated : False\ntheorem real : True := trivial",
            'def label := "protected axioms fabricated : False"',
        ):
            code = verifier.lean_code_without_comments_or_strings(harmless)
            self.assertFalse(verifier.has_forbidden_lean_construct(code))
        inline_bypass = verifier.lean_code_without_comments_or_strings(
            "#print axioms Nat.add_comm axiom hidden : False"
        )
        self.assertTrue(verifier.has_forbidden_lean_construct(inline_bypass))

    def test_outer_source_closure_rejects_multiline_import_and_late_implemented_by(self):
        verifier = load_verifier(self)
        for source in (
            "import\n  JackalIv.HiddenRuntime\n",
            "import Mathlib import\n  JackalIv.HiddenRuntime\n",
            "prelude import JackalIv.HiddenRuntime\n",
            "module\npublic import JackalIv.HiddenRuntime\n",
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                verifier.parse_lean_imports(
                    verifier.lean_code_without_comments_or_strings(source)
                )
        code = verifier.lean_code_without_comments_or_strings(
            "@[simp, implemented_by hiddenImpl] def checked : Nat := 0\n"
        )
        self.assertTrue(verifier.has_forbidden_lean_construct(code))

    def test_existing_local_module_cannot_be_relabelled_as_external(self):
        verifier = load_verifier(self)
        self.assertTrue(
            verifier.repository_local_lean_module_exists(
                PROOF_IDENTITY, "JackalIv.Spacecraft.Interval"
            )
        )
        self.assertFalse(
            verifier.repository_local_lean_module_exists(
                PROOF_IDENTITY, "Mathlib.Analysis.ODE.PicardLindelof"
            )
        )

    def test_exact_symbolic_orbital_identities_hold(self):
        verifier = load_verifier(self)
        results = verifier.verify_symbolic_identities()
        self.assertTrue(results)
        self.assertTrue(all(results.values()))
        self.assertIn("vis_viva_cleared_denominator_identity", results)
        self.assertIn("eccentricity_energy_momentum_identity", results)
        self.assertNotIn("vis_viva_cleared_denominator_expansion", results)
        self.assertNotIn("energy_definition_substitution", results)

    def test_checker_acceptance_line_requires_exact_contract(self):
        verifier = load_verifier(self)
        accepted = (
            "ACCEPT theorem=spacecraft_burn_certified_safe status=formal-bounded "
            "margin_lo=1 margin_hi=2 model=" + MODEL_ID + " epoch=" + EPOCH
        )
        self.assertTrue(verifier.checker_acceptance_line(accepted, MODEL_ID, EPOCH))
        for rejected in (
            "REJECT request-digest",
            accepted.replace("margin_lo=1", "margin_lo=0"),
            accepted.replace("model=" + MODEL_ID, "model=wrong"),
            accepted + " appended",
        ):
            with self.subTest(rejected=rejected):
                self.assertFalse(verifier.checker_acceptance_line(rejected, MODEL_ID, EPOCH))

    def test_formal_margin_must_equal_independent_global_hull(self):
        verifier = load_verifier(self)
        expected = {"post": {"margin_intersection": (11, 29)}}
        self.assertTrue(verifier.formal_margin_matches_replay((11, 29), expected))
        self.assertFalse(verifier.formal_margin_matches_replay((11, 28), expected))
        self.assertFalse(verifier.formal_margin_matches_replay((10, 29), expected))

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        verifier = load_verifier(self)
        for raw in (
            b'{"a":1,"a":2}',
            b'{"a":NaN}',
            b'{"a":Infinity}',
            b"1.0",
            b"1e309",
            b"-1e309",
            b"9" * (verifier.MAX_JSON_INTEGER_DIGITS + 1),
            b'{"x":"\\ud800"}',
            b'{"\\udfff":0}',
            b'{"x":[{"y":"\\ud800"}]}',
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                verifier.strict_json_bytes(raw)

    def test_strict_json_rejects_excessive_nesting(self):
        verifier = load_verifier(self)
        admitted_depth = verifier.MAX_JSON_NESTING_DEPTH
        admitted = b"[" * admitted_depth + b"0" + b"]" * admitted_depth
        self.assertIsInstance(verifier.strict_json_bytes(admitted), list)
        for depth in (verifier.MAX_JSON_NESTING_DEPTH + 1, 5000):
            raw = b"[" * depth + b"0" + b"]" * depth
            with self.subTest(depth=depth), self.assertRaises(ValueError):
                verifier.strict_json_bytes(raw)

    def test_malformed_receipt_request_and_identity_refuse_without_traceback(self):
        verifier = load_verifier(self)
        malformed = (
            b"[" * 5000 + b"0" + b"]" * 5000,
            b'{"x":"\\ud800"}',
            b"1e309",
            b"9" * (verifier.MAX_JSON_INTEGER_DIGITS + 1),
        )
        for index, raw in enumerate(malformed):
            with self.subTest(index=index), tempfile.TemporaryDirectory(
                prefix="malformed-json-refusal-"
            ) as directory:
                temporary = Path(directory)
                receipt_path = temporary / "receipt.json"
                request_path = temporary / "request.json"
                identity_path = temporary / "identity.json"
                for path in (receipt_path, request_path, identity_path):
                    path.write_bytes(raw)

                receipt_result = verifier.verify_receipt(
                    receipt_path,
                    CERTIFIER,
                    request_path=ROOT / "request_v2.json",
                )
                request_result = verifier.verify_receipt(
                    ROOT / "evidence/baseline_receipt_v2.json",
                    CERTIFIER,
                    request_path=request_path,
                    expected_request_digest=hashlib.sha256(raw).hexdigest(),
                )
                identity_reasons: list[str] = []
                identity_result = verifier.verify_identity_file(
                    identity_path,
                    hashlib.sha256(raw).hexdigest(),
                    "0" * 64,
                    "0" * 64,
                    "0" * 64,
                    MODEL_ID,
                    EPOCH,
                    identity_reasons,
                )

                self.assertEqual(
                    receipt_result,
                    {"status": "REFUSED", "reasons": ["invalid-receipt-json"]},
                )
                self.assertEqual(
                    request_result,
                    {"status": "REFUSED", "reasons": ["request-file-invalid"]},
                )
                self.assertIsNone(identity_result)
                self.assertEqual(identity_reasons, ["proof-identity-invalid"])

    def test_interval_receipt_requires_exact_directed_decimal_representations(self):
        verifier = load_verifier(self)
        interval = (1, 3)
        document = verifier.interval_document(interval)
        reasons: list[str] = []
        self.assertEqual(
            verifier.parse_receipt_interval(document, reasons, "fixture"), interval
        )
        self.assertEqual(reasons, [])
        for field in (
            "lo_scaled_integer",
            "hi_scaled_integer",
            "lo_exact",
            "hi_exact",
            "lo_decimal",
            "hi_decimal",
        ):
            mutated = {**document, field: document[field] + "0"}
            observed: list[str] = []
            self.assertIsNone(
                verifier.parse_receipt_interval(mutated, observed, "fixture")
            )
            self.assertEqual(observed, ["invalid-interval:fixture"])

        oversized = {
            **document,
            "lo_scaled_integer": "9" * (verifier.MAX_EXACT_INTEGER_DIGITS + 1),
        }
        observed = []
        self.assertIsNone(
            verifier.parse_receipt_interval(oversized, observed, "fixture")
        )
        self.assertEqual(observed, ["invalid-interval:fixture"])

    def test_checker_result_line_integer_tokens_are_explicitly_bounded(self):
        verifier = load_verifier(self)
        prefix = (
            "ACCEPT theorem=spacecraft_burn_certified_safe status=formal-bounded "
        )
        valid = (
            prefix
            + f"margin_lo=1 margin_hi=2 model={MODEL_ID} epoch={EPOCH}"
        )
        self.assertEqual(
            verifier.checker_acceptance_margin(valid, MODEL_ID, EPOCH), (1, 2)
        )
        oversized = "9" * (verifier.MAX_EXACT_INTEGER_DIGITS + 1)
        invalid = (
            prefix
            + f"margin_lo={oversized} margin_hi={oversized} "
            + f"model={MODEL_ID} epoch={EPOCH}"
        )
        self.assertIsNone(
            verifier.checker_acceptance_margin(invalid, MODEL_ID, EPOCH)
        )

    def test_expected_receipt_document_is_type_and_shape_exact_at_every_leaf(self):
        verifier = load_verifier(self)
        orbit_names = (
            "radius", "speed_squared", "energy", "semimajor_axis",
            "angular_momentum", "eccentricity_squared", "eccentricity",
            "eccentricity_vector_squared", "eccentricity_vector",
            "eccentricity_intersection", "apoapsis_formula", "apoapsis",
            "altitude_formula", "altitude", "margin_formula",
            "margin_intersection",
        )
        replay = {
            "trace_sha256": "1" * 64,
            "branch_count": 32,
            "tube_count": 124416,
            "postprocess_count": 3072,
            "maximum_picard_iterations": 1,
            "cutoff": ((1, 2),) * 5,
            "post": {name: (1, 2) for name in orbit_names},
            "minimum_cell": (1, 2),
            "minimum_formula_lo": 1,
            "minimum_location": {
                "branch_index": 0,
                "step_index": 3792,
                "time_lo_exact": "237/2",
                "time_hi_exact": "3793/32",
            },
            "domain_lower_bounds": {
                "radius_squared_exact": "1",
                "speed_squared_exact": "1",
                "mass_exact": "1",
            },
        }
        document = verifier.expected_receipt_document(
            replay,
            source_digest="2" * 64,
            witness_digest="3" * 64,
            witness_byte_size=99,
            checker_digest="4" * 64,
            proof_file_digest="5" * 64,
            proof_identity_digest="6" * 64,
            request_digest="7" * 64,
            model_id=MODEL_ID,
            epoch=EPOCH,
            nonce=NONCE,
            result_line=(
                "ACCEPT theorem=spacecraft_burn_certified_safe status=formal-bounded "
                f"margin_lo=1 margin_hi=2 model={MODEL_ID} epoch={EPOCH}"
            ),
            formal_margin=(1, 2),
        )
        self.assertEqual(set(document), verifier.RECEIPT_TOP_LEVEL_KEYS)
        self.assertIn(PICARD_PRODUCER_NONCLAIM, document["non_claims"])
        self.assertIsNone(verifier.first_difference(document, copy.deepcopy(document)))

        def leaves(value, path=()):
            if isinstance(value, dict):
                for key, item in value.items():
                    yield from leaves(item, (*path, key))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    yield from leaves(item, (*path, index))
            else:
                yield path, value

        def replace(value, path, replacement):
            target = value
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = replacement

        for path, value in leaves(document):
            mutated = copy.deepcopy(document)
            replacement = (
                not value if type(value) is bool
                else False if type(value) is int
                else value + "-mutated"
            )
            replace(mutated, path, replacement)
            with self.subTest(path=path):
                self.assertIsNotNone(verifier.first_difference(document, mutated))

    def test_legacy_v1_receipt_is_never_promoted(self):
        verifier = load_verifier(self)
        result = verifier.verify_receipt(BASELINE, CERTIFIER)
        self.assertEqual(result["status"], "REFUSED", result)
        self.assertEqual(result["reasons"], ["legacy-unproved-verdict-schema"])

    def test_v2_candidate_without_formal_binding_is_refused(self):
        verifier = load_verifier(self)
        payload = json.loads(BASELINE.read_text())
        payload["schema"] = "spacecraft-finite-burn-formal-receipt-v2"
        payload["verdict"] = "CERTIFIED SAFE"
        payload["verdict_qualifier"] = (
            "under the stated finite-burn ODE model, supplied input bounds, "
            "and machine-checked interval-certificate assumptions"
        )
        payload["producer_assurance"] = "candidate-only"
        payload["formal_checker_status"] = "NOT_EXECUTED"
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate.json"
            candidate.write_text(json.dumps(payload), encoding="utf-8")
            result = verifier.verify_receipt(candidate, CERTIFIER)
        self.assertEqual(result["status"], "REFUSED")
        self.assertEqual(result["reasons"], ["formal-checker-not-bound"])

    def test_malformed_replay_sections_refuse_without_traceback(self):
        verifier = load_verifier(self)
        reasons = {
            "method": "invalid-method-section",
            "cutoff_state_hull": "invalid-cutoff-state-hull",
            "orbital_hulls": "invalid-orbital-hulls",
        }
        with tempfile.TemporaryDirectory() as directory:
            for field, reason in reasons.items():
                with self.subTest(field=field):
                    payload = {
                        "schema": "spacecraft-finite-burn-formal-receipt-v2",
                        "formal_checker_status": "ACCEPT",
                        "method": {}, "cutoff_state_hull": {}, "orbital_hulls": {},
                    }
                    payload[field] = []
                    path = Path(directory) / f"{field}.json"
                    path.write_text(json.dumps(payload))
                    result = verifier.verify_receipt(path, CERTIFIER)
                    self.assertEqual(result, {"status": "REFUSED", "reasons": [reason]})

    def test_caller_supplied_symlink_is_refused_before_resolution(self):
        verifier = load_verifier(self)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.cert"
            target.write_text("witness\n")
            link = Path(directory) / "link.cert"
            link.symlink_to(target)
            result = verifier.verify_receipt(BASELINE, CERTIFIER, witness_path=link)
            self.assertEqual(result, {"status": "REFUSED", "reasons": ["witness-unreadable"]})

    @unittest.skipUnless(CHECKER.is_file(), "Lean checker binary is not built")
    def test_formal_binding_mutations_refuse_with_stable_reasons(self):
        verifier = load_verifier(self)
        self.assertTrue(PROOF_IDENTITY.is_file())
        self.assertTrue(CHECKER.is_file())
        identity = json.loads(PROOF_IDENTITY.read_text(encoding="utf-8"))
        proof_file_digest = sha(PROOF_IDENTITY)
        proof_internal_digest = identity["identity_digest_sha256"]
        mutations = {
            "checker_sha256": ("0" * 64, "checker-hash-mismatch"),
            "proof_identity_file_sha256": ("0" * 64, "proof-identity-file-hash-mismatch"),
            "proof_identity_digest_sha256": ("0" * 64, "proof-identity-internal-digest-mismatch"),
            "witness_sha256": ("0" * 64, "witness-hash-mismatch"),
            "request_digest": ("0" * 64, "request-digest-mismatch"),
            "model_id": ("wrong-model", "model-id-mismatch"),
            "epoch": ("wrong-epoch", "release-epoch-mismatch"),
            "nonce": ("wrong-nonce", "nonce-mismatch"),
            "theorem": ("wrong_theorem", "theorem-name-mismatch"),
            "result_line": ("bad\nline", "checker-result-line-invalid"),
        }
        with tempfile.TemporaryDirectory(prefix="spacecraft-binding-") as directory:
            temp = Path(directory)
            witness = temp / "witness.cert"
            witness.write_text("fixture-witness\n", encoding="ascii")
            base_binding = {
                "checker_sha256": sha(CHECKER),
                "proof_identity_file_sha256": proof_file_digest,
                "proof_identity_digest_sha256": proof_internal_digest,
                "witness_sha256": sha(witness),
                "request_digest": REQUEST_DIGEST,
                "model_id": MODEL_ID,
                "epoch": EPOCH,
                "nonce": NONCE,
                "theorem": "spacecraft_burn_certified_safe",
                "result_line": "not-invoked-because-each-case-refuses-before-execution",
            }
            for field, (mutated, reason) in mutations.items():
                with self.subTest(field=field):
                    candidate = {
                        "verdict_qualifier": QUALIFIER,
                        "formal_checker": {**base_binding, field: mutated},
                    }
                    receipt = temp / f"{field}.json"
                    receipt.write_text(json.dumps(candidate, sort_keys=True), encoding="utf-8")
                    reasons, _digests = verifier.verify_formal_binding(
                        candidate,
                        receipt,
                        witness_path=witness,
                        checker_path=CHECKER,
                        proof_identity_path=PROOF_IDENTITY,
                        expected_receipt_sha256=sha(receipt),
                        expected_proof_file_sha256=proof_file_digest,
                        expected_proof_identity_sha256=proof_internal_digest,
                        expected_request_digest=REQUEST_DIGEST,
                        expected_model_id=MODEL_ID,
                        expected_epoch=EPOCH,
                        nonce=NONCE,
                    )
                    self.assertIn(reason, reasons)

            candidate = {"verdict_qualifier": QUALIFIER, "formal_checker": base_binding}
            receipt = temp / "receipt-digest.json"
            receipt.write_text(json.dumps(candidate, sort_keys=True), encoding="utf-8")
            reasons, _digests = verifier.verify_formal_binding(
                candidate,
                receipt,
                witness_path=witness,
                checker_path=CHECKER,
                proof_identity_path=PROOF_IDENTITY,
                expected_receipt_sha256="0" * 64,
                expected_proof_file_sha256=proof_file_digest,
                expected_proof_identity_sha256=proof_internal_digest,
                expected_request_digest=REQUEST_DIGEST,
                expected_model_id=MODEL_ID,
                expected_epoch=EPOCH,
                nonce=NONCE,
            )
            self.assertIn("receipt-hash-mismatch", reasons)

            mutated_identity = json.loads(PROOF_IDENTITY.read_text(encoding="utf-8"))
            mutated_identity["fragment"]["soundness_theorem"] = "wrong_theorem"
            body = {key: value for key, value in mutated_identity.items()
                    if key != "identity_digest_sha256"}
            mutated_identity["identity_digest_sha256"] = hashlib.sha256(
                verifier.canonical_json_bytes(body)
            ).hexdigest()
            identity_path = temp / "mutated-identity.json"
            identity_path.write_text(
                json.dumps(mutated_identity, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            candidate = {
                "verdict_qualifier": QUALIFIER,
                "formal_checker": {
                    **base_binding,
                    "proof_identity_file_sha256": sha(identity_path),
                    "proof_identity_digest_sha256": mutated_identity["identity_digest_sha256"],
                },
            }
            receipt = temp / "identity-theorem.json"
            receipt.write_text(json.dumps(candidate, sort_keys=True), encoding="utf-8")
            reasons, _digests = verifier.verify_formal_binding(
                candidate,
                receipt,
                witness_path=witness,
                checker_path=CHECKER,
                proof_identity_path=identity_path,
                expected_receipt_sha256=sha(receipt),
                expected_proof_file_sha256=sha(identity_path),
                expected_proof_identity_sha256=mutated_identity["identity_digest_sha256"],
                expected_request_digest=REQUEST_DIGEST,
                expected_model_id=MODEL_ID,
                expected_epoch=EPOCH,
                nonce=NONCE,
            )
            self.assertIn("proof-identity-fragment-mismatch", reasons)


if __name__ == "__main__":
    unittest.main()
