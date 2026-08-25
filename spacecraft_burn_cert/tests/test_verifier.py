from __future__ import annotations

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
            return subprocess.CompletedProcess(command, 0, "ACCEPT\n", "")

        with mock.patch.object(verifier.subprocess, "run", side_effect=fake_run):
            completed = verifier.run_checker_snapshot(
                checker_bytes, witness_bytes, "request", "model", "epoch", 10
            )
        self.assertEqual(completed.stdout, "ACCEPT\n")
        self.assertEqual(observed, {
            "checker": checker_bytes,
            "witness": witness_bytes,
            "private": True,
        })

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
        real_resolve = verifier.resolve_identity_bound_path
        with tempfile.TemporaryDirectory() as directory:
            substitute = Path(directory) / "gaussian_proof_identity.py"
            substitute.write_text("# substituted identity engine\n", encoding="utf-8")

            def resolve(identity_path, recorded):
                if recorded == "release/tools/gaussian_proof_identity.py":
                    return substitute
                return real_resolve(identity_path, recorded)

            reasons: list[str] = []
            with mock.patch.object(
                verifier, "resolve_identity_bound_path", side_effect=resolve
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
                source,
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
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                verifier.strict_json_bytes(raw)

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
