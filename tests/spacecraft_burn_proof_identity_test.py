from __future__ import annotations

from contextlib import ExitStack
import functools
import importlib.util
import hashlib
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "release" / "tools" / "spacecraft_burn_proof_identity.py"
IDENTITY = ROOT / "release" / "evidence" / "spacecraft_burn_proof_identity_v1.json"
OWNING_PLATFORM_PYTHON = Path("/usr/bin/python3")
COMMITTED_IDENTITY_SHA256 = (
    "dc786a6e73a01278b09b899abd54555a5d268a305d745f66c4bf5480527bf876"
)


def committed_platform_launcher_records(
    identity_path: Path = IDENTITY,
) -> list[dict]:
    raw = identity_path.read_bytes()
    observed_digest = hashlib.sha256(raw).hexdigest()
    if observed_digest != COMMITTED_IDENTITY_SHA256:
        raise AssertionError(
            "proof identity file SHA-256 mismatch: "
            f"expected={COMMITTED_IDENTITY_SHA256} observed={observed_digest}"
        )

    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate proof identity key: {key}")
            result[key] = value
        return result

    document = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=reject_duplicates,
    )
    if type(document) is not dict:
        raise AssertionError("proof identity root is not an object")
    try:
        records = document["build_attestation"]["build_environment"][
            "trusted_platform_launchers"
        ]
    except (KeyError, TypeError) as error:
        raise AssertionError(
            "proof identity trusted platform launcher list is missing"
        ) from error
    if type(records) is not list or not records:
        raise AssertionError(
            "proof identity trusted platform launcher list is invalid"
        )
    return records


def platform_launcher_mismatch(wrapper, records: object) -> str | None:
    keys = {
        "bytes",
        "invocation_path",
        "invocation_symlink_target",
        "resolved_path",
        "role",
        "sha256",
    }
    if type(records) is not list or not records or len(records) > 16:
        raise AssertionError("trusted platform launcher list is invalid")
    roles: set[str] = set()
    diagnostics: list[str] = []
    for expected in records:
        if (
            type(expected) is not dict
            or set(expected) != keys
            or type(expected.get("bytes")) is not int
            or expected["bytes"] <= 0
            or type(expected.get("invocation_path")) is not str
            or not expected["invocation_path"]
            or type(expected.get("resolved_path")) is not str
            or not expected["resolved_path"]
            or type(expected.get("role")) is not str
            or not expected["role"]
            or type(expected.get("sha256")) is not str
            or len(expected["sha256"]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in expected["sha256"]
            )
            or (
                expected.get("invocation_symlink_target") is not None
                and type(expected.get("invocation_symlink_target")) is not str
            )
        ):
            raise AssertionError("trusted platform launcher record is malformed")
        role = expected["role"]
        if role in roles:
            raise AssertionError(f"duplicate trusted platform launcher role: {role}")
        roles.add(role)
        observed = wrapper.trusted_platform_launcher(
            role,
            Path(expected["invocation_path"]),
        )
        if observed != expected:
            differing_fields = sorted(
                key for key in keys if observed.get(key) != expected.get(key)
            )
            diagnostics.append(
                f"role={role} "
                f"expected_sha256={expected['sha256']} "
                f"observed_sha256={observed.get('sha256')} "
                f"differing_fields={','.join(differing_fields)}"
            )
    return "; ".join(diagnostics) if diagnostics else None


def hosted_macos_mismatch_is_skippable(environment: object) -> bool:
    return (
        type(environment) is dict
        and environment.get("GITHUB_ACTIONS") == "true"
        and environment.get("RUNNER_OS") == "macOS"
    )


def requires_exact_owning_platform_launchers(test):
    @functools.wraps(test)
    def wrapped(self, *args, **kwargs):
        if sys.platform != "darwin" or platform.machine() != "arm64":
            self.skipTest("committed executable identity is macOS/arm64-specific")
        wrapper = self.load_wrapper()
        records = committed_platform_launcher_records()
        diagnostic = platform_launcher_mismatch(wrapper, records)
        if diagnostic is not None:
            if hosted_macos_mismatch_is_skippable(dict(os.environ)):
                self.skipTest(diagnostic)
            self.fail(diagnostic)
        return test(self, *args, **kwargs)

    return wrapped


class SpacecraftProofIdentityTests(unittest.TestCase):
    def load_wrapper(self):
        sys.path.insert(0, str(SCRIPT.parent))
        try:
            spec = importlib.util.spec_from_file_location(
                "spacecraft_identity_wrapper_test", SCRIPT
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        finally:
            sys.path.pop(0)

    def run_gate(
        self, *args: str, interpreter: Path | str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(interpreter or sys.executable), "-I", "-B", str(SCRIPT), *args],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_committed_source_and_proof_identity_reproduce_cross_platform(self) -> None:
        result = self.run_gate("check", "--proof-only")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS spacecraft-burn proof identity", result.stdout)

    @requires_exact_owning_platform_launchers
    def test_committed_checker_binary_identity_reproduces_on_owning_platform(self) -> None:
        result = self.run_gate("check", interpreter=OWNING_PLATFORM_PYTHON)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("checker build binding", result.stdout)

    def test_mutated_checker_identity_refuses(self) -> None:
        document = json.loads(IDENTITY.read_text(encoding="utf-8"))
        document["checker"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory(prefix="spacecraft-proof-id-") as directory:
            candidate = Path(directory) / "identity.json"
            candidate.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
            result = self.run_gate("check", "--identity", str(candidate))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("identity self-digest mismatch", result.stderr)

    def test_wrapper_rejects_lane_override(self) -> None:
        result = self.run_gate("check", "--lane=gaussian")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixed to spacecraft-burn", result.stderr)

    def test_identity_engine_json_loader_is_bounded_and_strict(self) -> None:
        wrapper = self.load_wrapper()
        malformed = (
            b"[" * 5000 + b"0" + b"]" * 5000,
            b'{"x":0,"x":1}',
            b'{"x":NaN}',
            b'{"x":1.5}',
            b'{"x":"\\ud800"}',
            b'{"x":' + b"9" * (wrapper.MAX_JSON_INTEGER_DIGITS + 1) + b"}",
        )
        for index, raw in enumerate(malformed):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "identity.json"
                path.write_bytes(raw)
                with self.assertRaises(wrapper.engine.GateError):
                    wrapper.strict_json_load(path)

    def test_identity_envelope_uses_the_exact_parsed_snapshot(self) -> None:
        wrapper = self.load_wrapper()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            original = b'{"snapshot":"original"}\n'
            path.write_bytes(original)
            document = wrapper.strict_json_load(path)
            path.write_bytes(b'{"snapshot":"replacement"}\n')
            observed = {}

            def verify(snapshot_path, record):
                observed["bytes"] = snapshot_path.read_bytes()
                observed["record"] = record
                return record

            with mock.patch.object(
                wrapper, "_verify_engine_identity_envelope", side_effect=verify
            ):
                self.assertEqual(
                    wrapper.verify_identity_envelope(path, document), document
                )
            self.assertEqual(observed, {"bytes": original, "record": document})

    def test_generator_rejects_multiline_import_and_all_hidden_runtime_constructs(self) -> None:
        wrapper = self.load_wrapper()
        with self.assertRaises(wrapper.engine.GateError):
            wrapper.parse_spacecraft_imports(
                SCRIPT,
                "import\n  JackalIv.HiddenRuntime\n",
            )
        with self.assertRaises(wrapper.engine.GateError):
            wrapper.parse_spacecraft_imports(
                SCRIPT,
                "import Mathlib import\n  JackalIv.HiddenRuntime\n",
            )
        with self.assertRaises(wrapper.engine.GateError):
            wrapper.parse_spacecraft_imports(
                SCRIPT,
                "prelude import JackalIv.HiddenRuntime\n",
            )
        with self.assertRaises(wrapper.engine.GateError):
            wrapper.parse_spacecraft_imports(
                SCRIPT,
                "module\npublic import JackalIv.HiddenRuntime\n",
            )
        for code in (
            "@[simp, implemented_by hiddenImpl] def checked : Nat := 0",
            "public axiom hidden : False",
            "@[deprecated] noncomputable axiom hidden : False",
            "#print axioms Nat.add_comm axiom hidden : False",
        ):
            with self.subTest(code=code):
                self.assertTrue(
                    wrapper.SPACECRAFT_IMPLEMENTED_BY_RE.search(code)
                    or wrapper.SPACECRAFT_AXIOM_DECLARATION_RE.search(code)
                )

    def test_generator_refuses_checker_root_or_dependency_configuration_drift(self) -> None:
        wrapper = self.load_wrapper()
        payloads = {
            path: (ROOT / path).read_bytes()
            for path in wrapper.PINNED_CONFIGURATION_SHA256
        }
        wrapper.validate_pinned_configuration_payloads(payloads)
        payloads["proofs/lean/lakefile.toml"] = payloads[
            "proofs/lean/lakefile.toml"
        ].replace(
            b'root = "JackalIv.Spacecraft.CertMain"',
            b'root = "JackalIv.Spacecraft.FakeMain"',
        )
        with self.assertRaises(wrapper.engine.GateError):
            wrapper.validate_pinned_configuration_payloads(payloads)

    def test_private_recording_does_not_resolve_live_generator_against_private_root(self) -> None:
        wrapper = self.load_wrapper()
        source_closure = {"files": [], "root_module": "Fixture"}
        toolchain = {"compiler": {"sha256": "1" * 64}}
        observed_compiler = {"sha256": "1" * 64}
        theorem_axioms = [{"axioms": [], "theorem": "fixture"}]
        previous_root = wrapper.engine.REPO_ROOT
        previous_file = wrapper.engine.__file__
        try:
            with tempfile.TemporaryDirectory(prefix="identity-private-record-") as directory:
                wrapper.engine.REPO_ROOT = Path(directory)
                wrapper.engine.__file__ = str(SCRIPT)
                with (
                    mock.patch.object(
                        wrapper.engine,
                        "collect_source_closure",
                        return_value=source_closure,
                    ),
                    mock.patch.object(
                        wrapper.engine,
                        "collect_toolchain",
                        return_value=(toolchain, observed_compiler),
                    ),
                    mock.patch.object(
                        wrapper.engine,
                        "run_axiom_audit",
                        return_value=theorem_axioms,
                    ),
                    mock.patch.object(
                        wrapper,
                        "_collect_engine_source_closure",
                        return_value=source_closure,
                        create=True,
                    ),
                    mock.patch.object(
                        wrapper,
                        "_collect_engine_toolchain",
                        return_value=(toolchain, observed_compiler),
                        create=True,
                    ),
                    mock.patch.object(
                        wrapper,
                        "_run_engine_axiom_audit",
                        return_value=theorem_axioms,
                        create=True,
                    ),
                    mock.patch.object(wrapper, "locked_packages", return_value=[]),
                    mock.patch.object(wrapper, "validate_spacecraft_package_checkouts"),
                ):
                    sections = wrapper.collect_spacecraft_proof_sections()
        finally:
            wrapper.engine.REPO_ROOT = previous_root
            wrapper.engine.__file__ = previous_file
        self.assertEqual(sections["source_closure"], source_closure)
        self.assertEqual(sections["toolchain"]["compiler"], toolchain["compiler"])
        self.assertEqual(sections["_observed_compiler"], observed_compiler)
        self.assertEqual(sections["proof"]["theorems"], theorem_axioms)
        self.assertEqual(
            [entry["path"] for entry in sections["generator"]["files"]],
            [
                "release/tools/spacecraft_burn_proof_identity.py",
                "release/tools/gaussian_proof_identity.py",
            ],
        )

    @unittest.skipUnless(
        (ROOT / "proofs/lean/.lake/packages").is_dir(),
        "Lake package directory is not built",
    )
    def test_dependency_verifier_rejects_assume_unchanged_byte_drift(self) -> None:
        wrapper = self.load_wrapper()
        packages = ROOT / "proofs" / "lean" / ".lake" / "packages"
        with tempfile.TemporaryDirectory(prefix="identity-hostile-", dir=packages) as directory:
            checkout = Path(directory)

            def git(*arguments: str) -> str:
                completed = subprocess.run(
                    ["/usr/bin/git", "-C", str(checkout), *arguments],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                return completed.stdout.strip()

            git("init", "-q")
            git("config", "user.name", "JACKAL test")
            git("config", "user.email", "jackal-test@example.invalid")
            payload = checkout / "Bound.lean"
            payload.write_text("theorem bound : True := trivial\n", encoding="utf-8")
            git("add", "Bound.lean")
            git("commit", "-q", "-m", "fixture")
            revision = git("rev-parse", "HEAD")
            record = wrapper.verify_git_dependency_checkout(checkout, revision)
            self.assertEqual(record["revision"], revision)
            git("update-index", "--assume-unchanged", "Bound.lean")
            payload.write_text("axiom hidden : False\n", encoding="utf-8")
            with self.assertRaisesRegex(wrapper.engine.GateError, "index hiding"):
                wrapper.verify_git_dependency_checkout(checkout, revision)

    def test_identity_generation_cleans_all_workspace_build_outputs(self) -> None:
        wrapper = self.load_wrapper()
        wrapper._CLEAN_REBUILD = True
        wrapper.engine.CHECKER_TARGET = "jackal_spacecraft_burn_check"
        with (
            mock.patch.object(wrapper, "locked_packages", return_value=[]),
            mock.patch.object(wrapper, "validate_spacecraft_package_checkouts") as validate,
            mock.patch.object(wrapper.engine, "run", return_value="") as run,
        ):
            wrapper.build_spacecraft_checker()
        self.assertEqual(validate.call_count, 3)
        self.assertEqual(run.call_args_list[0].args[0], ["lake", "clean"])
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["lake", "build", "jackal_spacecraft_burn_check"],
        )

    def test_private_source_snapshot_admits_only_the_explicit_closure(self) -> None:
        wrapper = self.load_wrapper()
        with tempfile.TemporaryDirectory(prefix="identity-source-allowlist-") as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "private"
            (source / "JackalIv").mkdir(parents=True)
            (source / "JackalIv/Root.lean").write_text(
                "theorem admitted : True := trivial\n",
                encoding="utf-8",
            )
            (source / "lakefile.toml").write_text("name = \"fixture\"\n", encoding="utf-8")
            (source / "lakefile.lean").write_text(
                "package malicious where\n",
                encoding="utf-8",
            )
            wrapper.snapshot_local_lean_workspace(
                source,
                destination,
                {Path("JackalIv/Root.lean"), Path("lakefile.toml")},
            )
            self.assertTrue((destination / "JackalIv/Root.lean").is_file())
            self.assertFalse((destination / "lakefile.lean").exists())
            outside = root / "outside"
            outside.mkdir()
            (outside / "Escaped.lean").write_text(
                "axiom escaped : False\n",
                encoding="utf-8",
            )
            os.symlink(outside, source / "Escaped")
            with self.assertRaisesRegex(wrapper.engine.GateError, "symlink"):
                wrapper.snapshot_local_lean_workspace(
                    source,
                    root / "private-escaped",
                    {Path("Escaped/Escaped.lean")},
                )

    def test_lake_commands_force_the_absolute_pinned_configuration(self) -> None:
        wrapper = self.load_wrapper()
        command = wrapper.configured_lake_command(
            ["lake", "build", "jackal_spacecraft_burn_check"],
            Path("/private/work/proofs/lean"),
            Path("/private/toolchain/bin"),
        )
        self.assertEqual(command[0], "/private/toolchain/bin/lake")
        self.assertIn("--file=/private/work/proofs/lean/lakefile.toml", command)
        self.assertIn("--rehash", command)
        self.assertIn("--reconfigure", command)
        self.assertIn("--no-cache", command)
        with self.assertRaises(wrapper.engine.GateError):
            wrapper.configured_lake_command(
                ["lake", "--file=lakefile.lean", "build"],
                Path("/private/work/proofs/lean"),
                Path("/private/toolchain/bin"),
            )
        package = {
            "config_file": "lakefile.toml",
            "inherited": True,
            "manifest_file": "lake-manifest.json",
            "name": "BoundDep",
            "scope": "verified",
            "subdirectory": "lean",
            "type": "git",
        }
        override = json.loads(wrapper.private_package_override_bytes([package]))
        self.assertEqual(override["version"], "1.2.0")
        self.assertEqual(
            override["packages"][0]["dir"],
            ".lake/packages/BoundDep/lean",
        )
        previous_active = wrapper._PRIVATE_BUILD_ACTIVE
        previous_override = wrapper._PRIVATE_PACKAGE_OVERRIDE_PATH
        try:
            wrapper._PRIVATE_BUILD_ACTIVE = True
            wrapper._PRIVATE_PACKAGE_OVERRIDE_PATH = Path("/private/inputs/packages.json")
            private_command = wrapper.configured_lake_command(
                ["lake", "clean"],
                Path("/private/work/proofs/lean"),
                Path("/private/toolchain/bin"),
            )
        finally:
            wrapper._PRIVATE_BUILD_ACTIVE = previous_active
            wrapper._PRIVATE_PACKAGE_OVERRIDE_PATH = previous_override
        self.assertIn("--packages=/private/inputs/packages.json", private_command)

    def test_complete_toolchain_snapshot_binds_nonlauncher_bytes(self) -> None:
        wrapper = self.load_wrapper()
        token = "leanprover/lean4:v4.32.0"
        with tempfile.TemporaryDirectory(prefix="identity-toolchain-") as directory:
            root = Path(directory)
            source = root / wrapper.toolchain_directory_name(token)
            destination = root / "private-toolchain"
            (source / "bin").mkdir(parents=True)
            (source / "lib/lean").mkdir(parents=True)
            for name in ("lake", "lean", "leanc"):
                path = source / "bin" / name
                path.write_bytes((name + "\n").encode("ascii"))
                path.chmod(0o755)
            library = source / "lib/lean/libleanshared.dylib"
            library.write_bytes(b"bound-library-bytes\n")
            expected = wrapper.snapshot_complete_toolchain(
                source,
                destination,
                token,
            )
            library_copy = destination / "lib/lean/libleanshared.dylib"
            library_copy.write_bytes(b"mutated-library-bytes\n")
            actual = wrapper.complete_toolchain_tree_record(destination, token)
            self.assertNotEqual(actual["aggregate_sha256"], expected["aggregate_sha256"])

    def test_dependency_symlink_snapshot_refuses_package_escape(self) -> None:
        wrapper = self.load_wrapper()
        with tempfile.TemporaryDirectory(prefix="identity-symlink-") as directory:
            root = Path(directory)
            package = root / "package"
            destination = root / "private"
            (package / "docs").mkdir(parents=True)
            (package / "README.md").write_text("bound\n", encoding="utf-8")
            safe = package / "docs" / "README.md"
            safe.symlink_to("../README.md")

            def oid(target: str) -> str:
                payload = os.fsencode(target)
                return hashlib.sha1(
                    b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
                ).hexdigest()

            wrapper.snapshot_symlink(
                safe,
                destination / "docs" / "README.md",
                oid("../README.md"),
                package,
            )
            self.assertEqual(
                os.readlink(destination / "docs" / "README.md"),
                "../README.md",
            )

            escaped = package / "escape"
            escaped.symlink_to("../outside")
            with self.assertRaisesRegex(wrapper.engine.GateError, "escapes package"):
                wrapper.snapshot_symlink(
                    escaped,
                    destination / "escape",
                    oid("../outside"),
                    package,
                )

    def test_private_package_layout_refuses_symlinked_configuration_paths(self) -> None:
        wrapper = self.load_wrapper()
        package = {
            "config_file": "lakefile.toml",
            "inherited": True,
            "manifest_file": "lake-manifest.json",
            "name": "BoundDep",
            "scope": "verified",
            "subdirectory": "lean",
            "type": "git",
        }
        with tempfile.TemporaryDirectory(prefix="identity-package-layout-") as directory:
            private_lean = Path(directory)
            package_root = private_lean / ".lake/packages/BoundDep"
            real = package_root / "real"
            real.mkdir(parents=True)
            (real / "lakefile.toml").write_text("name = 'fixture'\n", encoding="utf-8")
            (real / "lake-manifest.json").write_text("{}\n", encoding="utf-8")
            (package_root / "lean").symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(wrapper.engine.GateError, "symlink"):
                wrapper.validate_private_package_layout(private_lean, package)

    def test_platform_launcher_binds_system_python_symlink_and_final_target(self) -> None:
        wrapper = self.load_wrapper()
        record = wrapper.trusted_platform_launcher(
            "python-interpreter",
            Path(sys.executable),
        )
        self.assertEqual(record["invocation_path"], os.path.abspath(sys.executable))
        self.assertEqual(record["resolved_path"], str(Path(sys.executable).resolve(strict=True)))
        self.assertGreater(record["bytes"], 0)
        self.assertRegex(record["sha256"], r"^[0-9a-f]{64}$")

    def test_platform_launchers_match_exact_bound_records(self) -> None:
        wrapper = self.load_wrapper()
        with tempfile.TemporaryDirectory(
            prefix="platform-launcher-match-"
        ) as directory:
            root = Path(directory)
            target = root / "launcher.bin"
            target.write_bytes(b"exact synthetic launcher bytes\n")
            invocation = root / "launcher"
            invocation.symlink_to(target.name)
            other_target = root / "other-launcher.bin"
            other_target.write_bytes(b"distinct observed launcher bytes\n")
            other_invocation = root / "other-launcher"
            other_invocation.symlink_to(other_target.name)
            record = wrapper.trusted_platform_launcher(
                "synthetic-launcher",
                invocation,
            )
            self.assertIsNone(platform_launcher_mismatch(wrapper, [record]))

            mutations = (
                ("sha256", "0" * 64),
                ("bytes", record["bytes"] + 1),
                ("invocation_path", str(root / "other-launcher")),
                ("resolved_path", str(root / "other-target")),
                ("invocation_symlink_target", "other-target"),
            )
            for field, replacement in mutations:
                with self.subTest(field=field):
                    changed = dict(record)
                    changed[field] = replacement
                    diagnostic = platform_launcher_mismatch(wrapper, [changed])
                    self.assertIsInstance(diagnostic, str)
                    expected_fields = (
                        ("sha256", "resolved_path")
                        if field == "invocation_path"
                        else (field,)
                    )
                    for expected_field in expected_fields:
                        self.assertIn(expected_field, diagnostic)

    def test_committed_launcher_records_require_independent_identity_pin(self) -> None:
        self.assertEqual(
            hashlib.sha256(IDENTITY.read_bytes()).hexdigest(),
            COMMITTED_IDENTITY_SHA256,
        )
        records = committed_platform_launcher_records(IDENTITY)
        self.assertTrue(records)
        with tempfile.TemporaryDirectory(
            prefix="launcher-identity-pin-"
        ) as directory:
            candidate = Path(directory) / "identity.json"
            candidate.write_bytes(b'{"build_attestation":{}}\n')
            with self.assertRaisesRegex(
                AssertionError,
                "proof identity file SHA-256",
            ):
                committed_platform_launcher_records(candidate)

    def test_launcher_mismatch_refuses_malformed_and_inspection_errors(self) -> None:
        wrapper = self.load_wrapper()
        with tempfile.TemporaryDirectory(
            prefix="launcher-mismatch-contract-"
        ) as directory:
            launcher = Path(directory) / "launcher"
            launcher.write_bytes(b"observed launcher bytes\n")
            record = wrapper.trusted_platform_launcher(
                "synthetic-launcher",
                launcher,
            )
            self.assertIsNone(platform_launcher_mismatch(wrapper, [record]))

            malformed = (
                [{key: value for key, value in record.items() if key != "sha256"}],
                [{**record, "bytes": False}],
                [record, dict(record)],
            )
            for records in malformed:
                with self.subTest(records=records), self.assertRaises(
                    (AssertionError, TypeError, ValueError)
                ):
                    platform_launcher_mismatch(wrapper, records)

            for error in (
                OSError("launcher unreadable"),
                wrapper.engine.GateError("launcher invalid"),
            ):
                with (
                    self.subTest(error=type(error).__name__),
                    mock.patch.object(
                        wrapper,
                        "trusted_platform_launcher",
                        side_effect=error,
                    ),
                    self.assertRaises(type(error)),
                ):
                    platform_launcher_mismatch(wrapper, [record])

    def test_later_launcher_inspection_error_overrides_earlier_mismatch(self) -> None:
        wrapper = self.load_wrapper()
        with tempfile.TemporaryDirectory(
            prefix="launcher-late-inspection-"
        ) as directory:
            root = Path(directory)
            first_path = root / "first-launcher"
            second_path = root / "second-launcher"
            first_path.write_bytes(b"first launcher bytes\n")
            second_path.write_bytes(b"second launcher bytes\n")
            first = wrapper.trusted_platform_launcher(
                "first-launcher",
                first_path,
            )
            second = wrapper.trusted_platform_launcher(
                "second-launcher",
                second_path,
            )
            first_mismatch = dict(first)
            first_mismatch["sha256"] = "0" * 64
            inspect = wrapper.trusted_platform_launcher

            for error in (
                OSError("later launcher unreadable"),
                wrapper.engine.GateError("later launcher invalid"),
            ):
                def inspect_all(role, path):
                    if role == "second-launcher":
                        raise error
                    return inspect(role, path)

                with (
                    self.subTest(error=type(error).__name__),
                    mock.patch.object(
                        wrapper,
                        "trusted_platform_launcher",
                        side_effect=inspect_all,
                    ),
                    self.assertRaises(type(error)),
                ):
                    platform_launcher_mismatch(
                        wrapper,
                        [first_mismatch, second],
                    )

    def test_observed_launcher_mismatch_has_exact_digest_diagnostic(self) -> None:
        wrapper = self.load_wrapper()
        with tempfile.TemporaryDirectory(
            prefix="launcher-mismatch-diagnostic-"
        ) as directory:
            launcher = Path(directory) / "launcher"
            launcher.write_bytes(b"observed launcher bytes\n")
            observed = wrapper.trusted_platform_launcher(
                "diagnostic-launcher",
                launcher,
            )
            expected = dict(observed)
            expected["sha256"] = "0" * 64
            diagnostic = platform_launcher_mismatch(wrapper, [expected])
        self.assertIsInstance(diagnostic, str)
        self.assertIn("diagnostic-launcher", diagnostic)
        self.assertIn(expected["sha256"], diagnostic)
        self.assertIn(observed["sha256"], diagnostic)

    def test_hosted_macos_mismatch_skip_policy_is_exact(self) -> None:
        cases = (
            (
                {"GITHUB_ACTIONS": "true", "RUNNER_OS": "macOS"},
                True,
            ),
            (
                {"GITHUB_ACTIONS": "false", "RUNNER_OS": "macOS"},
                False,
            ),
            (
                {"GITHUB_ACTIONS": "true", "RUNNER_OS": "Linux"},
                False,
            ),
            ({}, False),
        )
        for environment, expected in cases:
            with self.subTest(environment=environment):
                self.assertEqual(
                    hosted_macos_mismatch_is_skippable(environment),
                    expected,
                )

    def test_owning_platform_decorator_skips_only_hosted_macos_mismatch(self) -> None:
        diagnostic = (
            "role=python-interpreter "
            "expected_sha256=" + "0" * 64 + " "
            "observed_sha256=" + "1" * 64
        )
        probe = requires_exact_owning_platform_launchers(
            lambda _self: None
        )

        def invoke(environment, assertion):
            with ExitStack() as stack:
                stack.enter_context(
                    mock.patch.object(sys, "platform", "darwin")
                )
                stack.enter_context(
                    mock.patch.object(
                        platform,
                        "machine",
                        return_value="arm64",
                    )
                )
                stack.enter_context(
                    mock.patch(
                        f"{__name__}.committed_platform_launcher_records",
                        return_value=[{"role": "python-interpreter"}],
                        create=True,
                    )
                )
                stack.enter_context(
                    mock.patch(
                        f"{__name__}.platform_launcher_mismatch",
                        return_value=diagnostic,
                        create=True,
                    )
                )
                stack.enter_context(
                    mock.patch.dict(
                        os.environ,
                        environment,
                        clear=True,
                    )
                )
                stack.enter_context(assertion)
                probe(self)

        invoke(
            {"GITHUB_ACTIONS": "true", "RUNNER_OS": "macOS"},
            self.assertRaises(unittest.SkipTest),
        )
        invoke(
            {},
            self.assertRaisesRegex(AssertionError, "python-interpreter"),
        )

    @unittest.skipUnless(sys.platform == "darwin", "sandbox-exec is macOS-specific")
    def test_private_sandbox_allows_build_outputs_and_refuses_source_writes(self) -> None:
        wrapper = self.load_wrapper()
        with tempfile.TemporaryDirectory(prefix="identity-sandbox-") as directory:
            root = Path(directory).resolve(strict=True)
            private_lean = root / "repo/proofs/lean"
            private_toolchain = root / "private-elan/toolchains/fake"
            private_toolchain.mkdir(parents=True)
            private_lean.mkdir(parents=True)
            source = private_lean / "Source.lean"
            source.write_text("theorem source : True := trivial\n", encoding="utf-8")
            proofwidgets = private_lean / ".lake/packages/proofwidgets/widget"
            proofwidgets.mkdir(parents=True)
            package_lock = proofwidgets / "package-lock.json"
            package_lock.write_text("{}\n", encoding="utf-8")
            packages = [{
                "name": "proofwidgets",
                "subdirectory": None,
                "type": "git",
            }]
            previous_home = wrapper._PRIVATE_PROCESS_HOME
            previous_tmp = wrapper._PRIVATE_PROCESS_TMP
            try:
                wrapper._PRIVATE_PROCESS_HOME = root / "process-home"
                wrapper._PRIVATE_PROCESS_TMP = root / "process-tmp"
                profile = wrapper.private_build_sandbox_profile(
                    private_lean,
                    private_toolchain,
                    packages,
                )
            finally:
                wrapper._PRIVATE_PROCESS_HOME = previous_home
                wrapper._PRIVATE_PROCESS_TMP = previous_tmp
            self.assertIn("(deny default)", profile)
            allowed = subprocess.run(
                [
                    "/usr/bin/sandbox-exec",
                    "-p",
                    profile,
                    "/bin/sh",
                    "-c",
                    'printf allowed > "$1/.lake/build/output"',
                    "sh",
                    str(private_lean),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            bookkeeping = subprocess.run(
                [
                    "/usr/bin/sandbox-exec",
                    "-p",
                    profile,
                    "/bin/sh",
                    "-c",
                    'printf 179e66574f04806e > "$1.hash"',
                    "sh",
                    str(package_lock),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(bookkeeping.returncode, 0, bookkeeping.stderr)
            blocked = subprocess.run(
                [
                    "/usr/bin/sandbox-exec",
                    "-p",
                    profile,
                    "/bin/sh",
                    "-c",
                    'printf blocked > "$1"',
                    "sh",
                    str(source),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertEqual(source.read_text(encoding="utf-8"), "theorem source : True := trivial\n")
            blocked_package = subprocess.run(
                [
                    "/usr/bin/sandbox-exec",
                    "-p",
                    profile,
                    "/bin/sh",
                    "-c",
                    'printf changed > "$1"',
                    "sh",
                    str(package_lock),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertNotEqual(blocked_package.returncode, 0)
            self.assertEqual(package_lock.read_text(encoding="utf-8"), "{}\n")

    def test_private_lake_bookkeeping_is_exact_and_required_after_build(self) -> None:
        wrapper = self.load_wrapper()
        with tempfile.TemporaryDirectory(prefix="identity-bookkeeping-") as directory:
            private_lean = Path(directory)
            bookkeeping = (
                private_lean
                / ".lake/packages/proofwidgets/widget/package-lock.json.hash"
            )
            bookkeeping.parent.mkdir(parents=True)
            wrapper.validate_private_lake_bookkeeping(
                private_lean, require_complete=False
            )
            with self.assertRaisesRegex(wrapper.engine.GateError, "missing"):
                wrapper.validate_private_lake_bookkeeping(
                    private_lean, require_complete=True
                )
            bookkeeping.write_bytes(b"wrong")
            with self.assertRaisesRegex(wrapper.engine.GateError, "drift"):
                wrapper.validate_private_lake_bookkeeping(
                    private_lean, require_complete=False
                )
            bookkeeping.write_bytes(b"179e66574f04806e")
            wrapper.validate_private_lake_bookkeeping(
                private_lean, require_complete=True
            )

    def test_atomic_writer_refuses_existing_explicit_output_and_symlink_parent(self) -> None:
        wrapper = self.load_wrapper()
        with tempfile.TemporaryDirectory(prefix="identity-output-") as directory:
            root = Path(directory).resolve(strict=True)
            existing = root / "identity.json"
            existing.write_bytes(b"old\n")
            with self.assertRaisesRegex(wrapper.engine.GateError, "already exists"):
                wrapper.write_payload_atomic(
                    existing,
                    b"new\n",
                    0o644,
                    allow_replace=False,
                )
            self.assertEqual(existing.read_bytes(), b"old\n")
            wrapper.write_payload_atomic(
                existing,
                b"replacement\n",
                0o644,
                allow_replace=True,
            )
            self.assertEqual(existing.read_bytes(), b"replacement\n")
            created = root / "created.json"
            wrapper.write_payload_atomic(
                created,
                b"created\n",
                0o644,
                allow_replace=False,
            )
            self.assertEqual(created.read_bytes(), b"created\n")
            real_parent = root / "real"
            real_parent.mkdir()
            linked_parent = root / "linked"
            os.symlink(real_parent, linked_parent)
            with self.assertRaisesRegex(wrapper.engine.GateError, "traverse symlinks"):
                wrapper.write_payload_atomic(
                    linked_parent / "new.json",
                    b"new\n",
                    0o644,
                    allow_replace=False,
                )


if __name__ == "__main__":
    unittest.main()
