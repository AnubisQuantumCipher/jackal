import dataclasses
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import plugins.jackel.scripts.verify_plugin as verifier
from plugins.jackel.scripts.verify_plugin import (
    ManifestError,
    ManifestRecord,
    aggregate_digest,
    parse_manifest,
    require_expected_aggregate,
    verify_manifest,
)


PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "jackel"
VERIFY_SCRIPT = PLUGIN_ROOT / "scripts" / "verify_plugin.py"


class PluginIdentityTests(unittest.TestCase):
    def write_file(self, root, relative_path, data):
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def manifest_line(self, path, data):
        return f"{hashlib.sha256(data).hexdigest()}  {path}"

    def write_manifest(self, root, lines, final_newline=True):
        content = "\n".join(lines)
        if final_newline:
            content += "\n"
        path = root / "PLUGIN_IDENTITY.sha256"
        path.write_text(content, encoding="utf-8", newline="")
        return path

    def test_valid_manifest_returns_frozen_sorted_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alpha = b"alpha\x00bytes"
            beta = b"beta\nbytes"
            self.write_file(root, "alpha.txt", alpha)
            self.write_file(root, "nested/beta.txt", beta)
            manifest = self.write_manifest(
                root,
                [
                    self.manifest_line("alpha.txt", alpha),
                    self.manifest_line("nested/beta.txt", beta),
                ],
            )

            records = verify_manifest(root, manifest)

            self.assertTrue(dataclasses.is_dataclass(ManifestRecord))
            self.assertTrue(ManifestRecord.__dataclass_params__.frozen)
            self.assertEqual([record.path for record in records], ["alpha.txt", "nested/beta.txt"])
            self.assertEqual(records, parse_manifest(manifest))
            with self.assertRaises(dataclasses.FrozenInstanceError):
                records[0].path = "changed.txt"

    def test_missing_file_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.write_manifest(root, [self.manifest_line("missing.txt", b"missing")])

            with self.assertRaises(ManifestError):
                verify_manifest(root, manifest)

    def test_digest_mismatch_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_file(root, "payload.txt", b"actual")
            manifest = self.write_manifest(root, [self.manifest_line("payload.txt", b"expected")])

            with self.assertRaises(ManifestError):
                verify_manifest(root, manifest)

    def test_duplicate_path_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = b"payload"
            self.write_file(root, "payload.txt", data)
            line = self.manifest_line("payload.txt", data)
            manifest = self.write_manifest(root, [line, line])

            with self.assertRaises(ManifestError):
                parse_manifest(manifest)

    def test_unsafe_paths_are_refused(self):
        unsafe_paths = ["../outside.txt", "/absolute.txt", "nested\\file.txt", "./dot.txt", "nested//empty.txt"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in unsafe_paths:
                with self.subTest(path=path):
                    manifest = self.write_manifest(root, [self.manifest_line(path, b"payload")])
                    with self.assertRaises(ManifestError):
                        parse_manifest(manifest)

    def test_plugin_directory_open_error_uses_manifest_error_taxonomy(self):
        with tempfile.TemporaryDirectory() as directory:
            root_fd = os.open(directory, verifier._open_flags(directory=True))
            try:
                with (
                    mock.patch.object(
                        verifier.os,
                        "open",
                        side_effect=OSError("fixture directory-open failure"),
                    ),
                    self.assertRaisesRegex(
                        verifier.UnexpectedEntry, "plugin inventory directory"
                    ),
                ):
                    verifier._open_plugin_directory_at(root_fd, "nested")
            finally:
                os.close(root_fd)

    def test_plugin_directory_dup_error_uses_manifest_error_taxonomy(self):
        with tempfile.TemporaryDirectory() as directory:
            root_fd = os.open(directory, verifier._open_flags(directory=True))
            try:
                with (
                    mock.patch.object(
                        verifier.os,
                        "dup",
                        side_effect=OSError("fixture directory-dup failure"),
                    ),
                    self.assertRaisesRegex(
                        verifier.UnexpectedEntry, "plugin inventory directory"
                    ),
                ):
                    verifier._open_plugin_directory_at(root_fd, "nested")
            finally:
                os.close(root_fd)

    def test_plugin_directory_close_error_does_not_mask_open_taxonomy(self):
        with tempfile.TemporaryDirectory() as directory:
            root_fd = os.open(directory, verifier._open_flags(directory=True))
            try:
                with (
                    mock.patch.object(verifier.os, "dup", return_value=424203),
                    mock.patch.object(
                        verifier.os,
                        "open",
                        side_effect=OSError("fixture directory-open failure"),
                    ),
                    mock.patch.object(
                        verifier.os,
                        "close",
                        side_effect=OSError("fixture directory-close failure"),
                    ),
                    self.assertRaisesRegex(
                        verifier.UnexpectedEntry, "plugin inventory directory"
                    ),
                ):
                    verifier._open_plugin_directory_at(root_fd, "nested")
            finally:
                os.close(root_fd)

    def test_plugin_file_dup_error_uses_manifest_error_taxonomy(self):
        with tempfile.TemporaryDirectory() as directory:
            root_fd = os.open(directory, verifier._open_flags(directory=True))
            try:
                with (
                    mock.patch.object(
                        verifier.os,
                        "dup",
                        side_effect=OSError("fixture file-dup failure"),
                    ),
                    self.assertRaisesRegex(
                        verifier.UnexpectedEntry, "plugin file"
                    ),
                ):
                    verifier._open_plugin_file_at(root_fd, "nested/file.txt")
            finally:
                os.close(root_fd)

    def test_plugin_inventory_dup_error_uses_manifest_error_taxonomy(self):
        with tempfile.TemporaryDirectory() as directory:
            root_fd = os.open(directory, verifier._open_flags(directory=True))
            try:
                with (
                    mock.patch.object(
                        verifier.os,
                        "dup",
                        side_effect=OSError("fixture inventory-dup failure"),
                    ),
                    self.assertRaisesRegex(
                        verifier.UnexpectedEntry, "plugin inventory"
                    ),
                ):
                    verifier._verify_exact_inventory_at(root_fd, ())
            finally:
                os.close(root_fd)

    def test_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.write_file(root, "real.txt", b"payload")
            link = root / "linked.txt"
            os.symlink(target, link)
            manifest = self.write_manifest(root, [self.manifest_line("linked.txt", b"payload")])

            with self.assertRaises(ManifestError):
                verify_manifest(root, manifest)

    def test_intermediate_directory_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = root / "external"
            external.mkdir()
            (external / "payload.txt").write_bytes(b"payload")
            os.symlink(external, root / "nested")
            manifest = self.write_manifest(root, [self.manifest_line("nested/payload.txt", b"payload")])

            with self.assertRaises(ManifestError):
                verify_manifest(root, manifest)

    def test_path_replacement_after_open_is_refused_by_final_exact_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "plugin"
            root.mkdir()
            original = b"original verified bytes"
            replacement = base / "external.txt"
            replacement.write_bytes(b"external replacement bytes")
            payload = self.write_file(root, "payload.txt", original)
            manifest = self.write_manifest(root, [self.manifest_line("payload.txt", original)])
            hash_open_file = verifier._hash_open_file

            def replace_name_then_hash(fd, *, byte_limit):
                payload.unlink()
                os.symlink(replacement, payload)
                return hash_open_file(fd, byte_limit=byte_limit)

            with mock.patch.object(verifier, "_hash_open_file", side_effect=replace_name_then_hash):
                with self.assertRaises(ManifestError):
                    verify_manifest(root, manifest)

            self.assertTrue(payload.is_symlink())

    def test_regular_path_replacement_after_hash_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = b"verified bytes"
            payload = self.write_file(root, "payload.txt", original)
            manifest = self.write_manifest(
                root, [self.manifest_line("payload.txt", original)]
            )
            hash_open_file = verifier._hash_open_file

            def replace_after_hash(fd, *, byte_limit):
                result = hash_open_file(fd, byte_limit=byte_limit)
                payload.unlink()
                payload.write_bytes(b"unverified regular replacement")
                return result

            with mock.patch.object(
                verifier, "_hash_open_file", side_effect=replace_after_hash
            ):
                with self.assertRaises(ManifestError):
                    verify_manifest(root, manifest)

    def test_coordinated_aba_mutation_after_hash_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "plugin"
            root.mkdir()
            original = b"verified-bytes"
            payload = self.write_file(root, "payload.txt", original)
            replacement = base / "replacement"
            replacement.write_bytes(b"transient replacement")
            parked = base / "parked-original"
            manifest = self.write_manifest(
                root, [self.manifest_line("payload.txt", original)]
            )
            hash_open_file = verifier._hash_open_file

            def mutate_after_aba(fd, *, byte_limit):
                result = hash_open_file(fd, byte_limit=byte_limit)
                if os.fstat(fd).st_ino == payload.stat().st_ino:
                    os.rename(payload, parked)
                    os.rename(replacement, payload)
                    os.rename(payload, replacement)
                    os.rename(parked, payload)
                return result

            with mock.patch.object(
                verifier, "_hash_open_file", side_effect=mutate_after_aba
            ):
                with self.assertRaises(ManifestError):
                    verify_manifest(root, manifest)

    def test_exact_inventory_rejects_every_unlisted_entry_kind(self):
        entry_kinds = ("regular", "directory", "symlink", "pycache")
        for entry_kind in entry_kinds:
            with self.subTest(entry_kind=entry_kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                payload = self.write_file(root, "payload.txt", b"payload")
                manifest = self.write_manifest(
                    root, [self.manifest_line("payload.txt", b"payload")]
                )
                if entry_kind == "regular":
                    self.write_file(root, "extra.txt", b"extra")
                elif entry_kind == "directory":
                    (root / "extra").mkdir()
                elif entry_kind == "symlink":
                    os.symlink(payload, root / "extra-link")
                else:
                    self.write_file(root, "__pycache__/payload.cpython-314.pyc", b"cache")

                with self.assertRaises(ManifestError):
                    verify_manifest(root, manifest)

    def test_exact_inventory_refuses_unlisted_fifo_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_file(root, "payload.txt", b"payload")
            manifest = self.write_manifest(
                root, [self.manifest_line("payload.txt", b"payload")]
            )
            os.mkfifo(root / "extra-fifo")
            program = (
                "import sys; from pathlib import Path; "
                "from plugins.jackel.scripts.verify_plugin import ManifestError, verify_manifest; "
                "\ntry: verify_manifest(Path(sys.argv[1]), Path(sys.argv[2]))"
                "\nexcept ManifestError: raise SystemExit(0)\nraise SystemExit(1)"
            )
            result = subprocess.run(
                [sys.executable, "-B", "-c", program, str(root), str(manifest)],
                cwd=PLUGIN_ROOT.parents[1], capture_output=True, check=False,
                text=True, timeout=1.0,
            )
            self.assertEqual(result.returncode, 0)

    def test_unsorted_entries_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_file(root, "alpha.txt", b"alpha")
            self.write_file(root, "beta.txt", b"beta")
            manifest = self.write_manifest(
                root,
                [self.manifest_line("beta.txt", b"beta"), self.manifest_line("alpha.txt", b"alpha")],
            )

            with self.assertRaises(ManifestError):
                parse_manifest(manifest)

    def test_malformed_hash_and_spacing_are_refused(self):
        valid_hash = hashlib.sha256(b"payload").hexdigest()
        malformed_lines = [
            f"{valid_hash.upper()}  payload.txt",
            f"{valid_hash[:-1]}  payload.txt",
            f"{valid_hash} payload.txt",
            f"{valid_hash}   payload.txt",
            f"{valid_hash}\tpayload.txt",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for line in malformed_lines:
                with self.subTest(line=line):
                    manifest = self.write_manifest(root, [line])
                    with self.assertRaises(ManifestError):
                        parse_manifest(manifest)

    def test_missing_final_newline_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.write_manifest(root, [self.manifest_line("payload.txt", b"payload")], final_newline=False)

            with self.assertRaises(ManifestError):
                parse_manifest(manifest)

    def test_empty_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "PLUGIN_IDENTITY.sha256"
            manifest.write_bytes(b"")

            with self.assertRaises(ManifestError):
                parse_manifest(manifest)

    def test_manifest_byte_limit_is_checked_before_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "PLUGIN_IDENTITY.sha256"
            with manifest.open("wb") as handle:
                handle.truncate(verifier.MAX_MANIFEST_BYTES + 1)

            with (
                mock.patch.object(verifier.os, "read", wraps=verifier.os.read) as read,
                self.assertRaises(ManifestError),
            ):
                parse_manifest(manifest)

            read.assert_not_called()

    def test_manifest_record_count_is_bounded_during_parse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lines = [
                self.manifest_line(f"payload-{index}.txt", b"payload")
                for index in range(2)
            ]
            manifest = self.write_manifest(root, lines)

            with (
                mock.patch.object(verifier, "MAX_INVENTORY_ENTRIES", 1),
                self.assertRaises(ManifestError),
            ):
                parse_manifest(manifest)

    def test_named_file_byte_limit_is_checked_before_hashing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "payload.txt"
            with payload.open("wb") as handle:
                handle.truncate(verifier.MAX_PLUGIN_FILE_BYTES + 1)
            manifest = self.write_manifest(
                root, [self.manifest_line("payload.txt", b"not-the-sparse-file")]
            )

            with (
                mock.patch.object(
                    verifier.hashlib, "sha256", wraps=verifier.hashlib.sha256
                ) as sha256,
                self.assertRaises(ManifestError),
            ):
                verify_manifest(root, manifest)

            # The manifest line helper hashes once before the verifier runs; the
            # oversized named file itself must be rejected without a hash object.
            self.assertEqual(sha256.call_count, 0)

    def test_named_file_aggregate_bytes_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = b"a" * 8
            second = b"b" * 8
            self.write_file(root, "first.txt", first)
            self.write_file(root, "second.txt", second)
            manifest = self.write_manifest(
                root,
                [
                    self.manifest_line("first.txt", first),
                    self.manifest_line("second.txt", second),
                ],
            )

            with (
                mock.patch.object(verifier, "MAX_PLUGIN_FILE_BYTES", 8),
                mock.patch.object(verifier, "MAX_PLUGIN_TOTAL_BYTES", 12),
                self.assertRaises(ManifestError),
            ):
                verify_manifest(root, manifest)

    def test_manifest_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "real-manifest"
            target.write_bytes(b"0" * 64 + b"  payload.txt\n")
            manifest = root / "PLUGIN_IDENTITY.sha256"
            os.symlink(target, manifest)

            with self.assertRaises(ManifestError):
                parse_manifest(manifest)

    def test_nonregular_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "PLUGIN_IDENTITY.sha256"
            manifest.mkdir()

            with self.assertRaises(ManifestError):
                parse_manifest(manifest)

    def test_fifo_manifest_is_refused_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "PLUGIN_IDENTITY.sha256"
            os.mkfifo(manifest)
            program = (
                "import sys; from plugins.jackel.scripts.verify_plugin import ManifestError, parse_manifest; "
                "\ntry: parse_manifest(sys.argv[1])\nexcept ManifestError: raise SystemExit(0)\nraise SystemExit(1)"
            )

            result = subprocess.run(
                [sys.executable, "-B", "-c", program, str(manifest)],
                cwd=PLUGIN_ROOT.parents[1],
                capture_output=True,
                check=False,
                text=True,
                timeout=1.0,
            )

            self.assertEqual(result.returncode, 0)

    def test_fifo_named_file_is_refused_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fifo = root / "payload.txt"
            os.mkfifo(fifo)
            manifest = self.write_manifest(root, [self.manifest_line("payload.txt", b"payload")])
            program = (
                "import sys; from pathlib import Path; "
                "from plugins.jackel.scripts.verify_plugin import ManifestError, verify_manifest; "
                "\ntry: verify_manifest(Path(sys.argv[1]), Path(sys.argv[2]))"
                "\nexcept ManifestError: raise SystemExit(0)\nraise SystemExit(1)"
            )

            result = subprocess.run(
                [sys.executable, "-B", "-c", program, str(root), str(manifest)],
                cwd=PLUGIN_ROOT.parents[1],
                capture_output=True,
                check=False,
                text=True,
                timeout=1.0,
            )

            self.assertEqual(result.returncode, 0)

    def test_ascii_control_characters_in_paths_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in ["bad\x1bpath.txt", "bad\x7fpath.txt"]:
                with self.subTest(path=repr(path)):
                    manifest = self.write_manifest(root, [self.manifest_line(path, b"payload")])
                    with self.assertRaises(ManifestError):
                        parse_manifest(manifest)

    def test_path_diagnostics_are_escaped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = "missing file.txt"
            manifest = self.write_manifest(root, [self.manifest_line(path, b"payload")])

            with self.assertRaises(ManifestError) as raised:
                verify_manifest(root, manifest)

            self.assertIn(repr(path), str(raised.exception))

    def test_aggregate_digest_has_stable_canonical_value(self):
        records = [
            ManifestRecord(path="alpha.txt", digest="a" * 64),
            ManifestRecord(path="beta.txt", digest="b" * 64),
        ]

        self.assertEqual(
            aggregate_digest(records),
            "343bbae5bf214ddb591d95c30bb8cc2f561145468f71889c21b5b5fe288eb09e",
        )

    def test_expected_aggregate_accepts_a_caller_pinned_value(self):
        records = [ManifestRecord(path="payload.txt", digest="a" * 64)]
        expected = aggregate_digest(records)

        self.assertEqual(require_expected_aggregate(records, expected), expected)

    def test_expected_aggregate_refuses_a_mismatch(self):
        records = [ManifestRecord(path="payload.txt", digest="a" * 64)]

        with self.assertRaises(ManifestError):
            require_expected_aggregate(records, "b" * 64)

    def test_expected_aggregate_refuses_invalid_expected_digest(self):
        records = [ManifestRecord(path="payload.txt", digest="a" * 64)]
        for expected in ["A" * 64, "a" * 63, "g" * 64]:
            with self.subTest(expected=expected):
                with self.assertRaises(ManifestError):
                    require_expected_aggregate(records, expected)

    def test_cli_success_is_exact_for_the_current_plugin_manifest(self):
        records = verify_manifest(PLUGIN_ROOT, PLUGIN_ROOT / "PLUGIN_IDENTITY.sha256")
        expected = aggregate_digest(records)

        result = subprocess.run(
            [sys.executable, str(VERIFY_SCRIPT)],
            cwd=PLUGIN_ROOT.parents[1],
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout,
            f"plugin_identity=verified files={len(records)} aggregate_sha256={expected}\n",
        )
        self.assertEqual(result.stderr, "")

    def test_cli_refusal_is_bounded_and_has_no_traceback(self):
        result = subprocess.run(
            [sys.executable, str(VERIFY_SCRIPT), "unexpected"],
            cwd=PLUGIN_ROOT.parents[1],
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertRegex(result.stderr, r"^plugin_identity=refused reason=UsageError detail=[^\n]+\n$")
        self.assertNotIn("Traceback", result.stderr)

    def test_main_reports_unexpected_failure_without_sensitive_detail(self):
        stderr = io.StringIO()
        with mock.patch.object(verifier, "verify_manifest", side_effect=RuntimeError("sensitive-token\nsecret")):
            with mock.patch("sys.stderr", stderr):
                exit_code = verifier.main([])

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            stderr.getvalue(),
            "plugin_identity=refused reason=internal-error detail=unexpected verification failure\n",
        )
        self.assertNotIn("Traceback", stderr.getvalue())
        self.assertNotIn("sensitive-token", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
