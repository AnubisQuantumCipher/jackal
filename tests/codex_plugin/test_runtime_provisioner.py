import errno
import hashlib
import io
import json
import os
import shlex
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from plugins.jackel.scripts import provision_runtime as provisioner


class FakeResponse:
    def __init__(self, data, content_length=None):
        self._data = io.BytesIO(data)
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return self._data.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False


class RuntimeProvisionerTests(unittest.TestCase):
    def sha(self, data):
        return hashlib.sha256(data).hexdigest()

    def add_bytes(self, archive, name, data=b"", mode=0o644, kind=tarfile.REGTYPE, linkname=""):
        info = tarfile.TarInfo(name)
        info.type = kind
        info.mode = mode
        info.linkname = linkname
        info.size = len(data) if kind == tarfile.REGTYPE else 0
        archive.addfile(info, io.BytesIO(data) if info.size else None)

    def package_files(self, marker=True, launcher=None):
        launcher = launcher or (
            b"#!/bin/sh\n"
            + (b"echo plugin_hermes.identity_match=true\nexit 0\n" if marker else b"echo no-marker\nexit 0\n")
        )
        files = {
            "MANIFEST.sha256": b"package manifest\n",
            "plugin/hermes/jackal_hermes": launcher,
            "payload.txt": b"payload\n",
        }
        checksums = "".join(
            f"{self.sha(data)}  ./{name}\n" for name, data in sorted(files.items())
        ).encode()
        files["SHA256SUMS"] = checksums
        return files

    def tar_tree_digest(self, tarball, top="jackal-v1.7.0-macos-arm64"):
        with tarfile.open(tarball, "r:*") as archive:
            source = archive.extractfile(f"{top}/SHA256SUMS")
            self.assertIsNotNone(source)
            return self.sha(source.read())

    def tar_extracted_size(self, tarball):
        with tarfile.open(tarball, "r:*") as archive:
            return sum(member.size for member in archive.getmembers() if member.isreg())

    def make_tarball(self, root, *, top="jackal-v1.7.0-macos-arm64", files=None):
        files = self.package_files() if files is None else files
        path = root / "fixture.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            directory = tarfile.TarInfo(top)
            directory.type = tarfile.DIRTYPE
            directory.mode = 0o755
            archive.addfile(directory)
            directories = set()
            for relative, data in files.items():
                parts = Path(relative).parts[:-1]
                for index in range(1, len(parts) + 1):
                    name = f"{top}/{'/'.join(parts[:index])}"
                    if name not in directories:
                        item = tarfile.TarInfo(name)
                        item.type = tarfile.DIRTYPE
                        item.mode = 0o755
                        archive.addfile(item)
                        directories.add(name)
                self.add_bytes(
                    archive,
                    f"{top}/{relative}",
                    data,
                    0o755 if relative == "plugin/hermes/jackal_hermes" else 0o644,
                )
        return path

    def provision_fixture(self, root, tarball, **overrides):
        target = root / "support" / "runtimes" / "v1.7.0"
        locator = root / "support" / "codex-plugin" / "runtime.json"
        data = tarball.read_bytes() if tarball is not None else b""
        tree_digest = overrides.get("expected_tree_sha256")
        if tree_digest is None:
            tree_digest = self.tar_tree_digest(tarball) if tarball is not None else self.sha(b"")
        arguments = dict(
            tarball=tarball,
            runtime_target=target,
            locator_path=locator,
            expected_size=len(data),
            expected_sha256=self.sha(data),
            expected_extracted_size=(self.tar_extracted_size(tarball) if tarball is not None else 0),
            expected_tree_sha256=tree_digest,
            expected_top_level="jackal-v1.7.0-macos-arm64",
            system="Darwin",
            machine="arm64",
        )
        arguments.update(overrides)
        result = provisioner.provision(**arguments)
        return result, target, locator

    def write_runtime_fixture(self, root, *, files=None):
        files = self.package_files() if files is None else files
        for name, data in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (root / "plugin/hermes/jackal_hermes").chmod(0o755)
        (root / ".jackal-package.json").write_text(
            '{"fixture":true}\n', encoding="utf-8",
        )
        return files

    def test_validate_host_accepts_only_darwin_arm64(self):
        provisioner.validate_host("Darwin", "arm64")
        for system, machine in (("Linux", "arm64"), ("Darwin", "x86_64"), ("Linux", "x86_64")):
            with self.subTest(system=system, machine=machine), self.assertRaises(provisioner.ProvisionError):
                provisioner.validate_host(system, machine)

    def test_runtime_subprocess_environment_is_minimal_and_preserves_only_jackal_home(self):
        source = {
            "PATH": "/tmp/hostile",
            "PYTHONPATH": "/tmp/inject",
            "PYTHONHOME": "/tmp/inject-home",
            "DYLD_INSERT_LIBRARIES": "/tmp/inject.dylib",
            "HOME": "/tmp/fake-home",
            "JACKAL_HOME": "/absolute/jackal-runtime",
            "JACKAL_UNRECOGNIZED": "must-not-leak",
        }

        result = provisioner.runtime_subprocess_environment(source)

        interpreter_directory = str(Path(sys.executable).parent)
        self.assertEqual(
            result,
            {
                "PATH": f"{interpreter_directory}:/usr/bin:/bin:/usr/sbin:/sbin",
                "JACKAL_HOME": "/absolute/jackal-runtime",
            },
        )

    def test_selftest_ignores_hostile_caller_path_python3(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hostile = root / "hostile"
            hostile.mkdir()
            attacked = root / "attacker-ran"
            fake_python = hostile / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                f"printf attacked > {shlex.quote(str(attacked))}\n"
                "echo plugin_hermes.identity_match=true\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            entry = root / "selftest.py"
            entry.write_text(
                "print('legitimate-selftest')\n"
                "print('plugin_hermes.identity_match=true')\n",
                encoding="utf-8",
            )
            launcher = root / "jackal_hermes"
            launcher.write_text(
                "#!/bin/sh\n"
                f"exec python3 -I -S -B {shlex.quote(str(entry))}\n",
                encoding="utf-8",
            )
            launcher.chmod(0o755)

            with mock.patch.dict(os.environ, {"PATH": str(hostile)}, clear=False):
                result = provisioner._run_selftest(
                    [str(launcher)], timeout=1.0, output_limit=1024
                )

            self.assertEqual(result.returncode, 0)
            self.assertIn("legitimate-selftest", result.stdout.splitlines())
            self.assertFalse(attacked.exists())

    def test_unsupported_host_refuses_before_opener(self):
        opener = mock.Mock(side_effect=AssertionError("must not download"))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(provisioner.ProvisionError):
                provisioner.provision(
                    runtime_target=Path(directory) / "runtime",
                    locator_path=Path(directory) / "locator.json",
                    expected_size=1,
                    expected_sha256=self.sha(b"x"),
                    opener=opener,
                    system="Linux",
                    machine="arm64",
                )
        opener.assert_not_called()

    def test_stream_download_requires_declared_exact_length(self):
        data = b"abcdef"
        for declared in (len(data) - 1, len(data) + 1):
            with self.subTest(declared=declared), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "download"
                response = FakeResponse(data, declared)
                with self.assertRaises(provisioner.ProvisionError):
                    provisioner.stream_download(
                        "https://example.invalid/asset", output,
                        expected_size=len(data), expected_sha256=self.sha(data),
                        opener=lambda unused, **kwargs: response,
                    )
                self.assertFalse(output.exists())
                self.assertEqual(response.read_sizes, [])

    def test_stream_download_rejects_over_limit_immediately_and_bounds_chunks(self):
        data = b"abcdefgh"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "download"
            response = FakeResponse(data)
            with self.assertRaises(provisioner.ProvisionError):
                provisioner.stream_download(
                    "https://example.invalid/asset", output,
                    expected_size=5, expected_sha256=self.sha(data[:5]),
                    opener=lambda unused, **kwargs: response, chunk_size=2,
                )
            self.assertFalse(output.exists())
            self.assertEqual(response.read_sizes, [2, 2, 2])
            self.assertTrue(all(size <= 2 for size in response.read_sizes))

    def test_stream_download_requires_exact_size_and_digest_and_cleans_output(self):
        cases = ((b"short", 6, self.sha(b"short!")), (b"abcdef", 6, self.sha(b"wrong")))
        for data, size, digest in cases:
            with self.subTest(data=data), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "download"
                with self.assertRaises(provisioner.ProvisionError):
                    provisioner.stream_download(
                        "https://example.invalid/asset", output,
                        expected_size=size, expected_sha256=digest,
                        opener=lambda unused, data=data, **kwargs: FakeResponse(data), chunk_size=2,
                    )
                self.assertFalse(output.exists())

    def test_stream_download_success(self):
        data = b"abcdef"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "download"
            response = FakeResponse(data, len(data))
            self.assertEqual(
                provisioner.stream_download(
                    "https://example.invalid/asset", output,
                    expected_size=len(data), expected_sha256=self.sha(data),
                    opener=lambda unused, **kwargs: response, chunk_size=2,
                ),
                output,
            )
            self.assertEqual(output.read_bytes(), data)
            self.assertTrue(all(size <= 2 for size in response.read_sizes))

    def test_stream_download_passes_bounded_network_timeout(self):
        data = b"payload"
        opener = mock.Mock(return_value=FakeResponse(data, len(data)))
        with tempfile.TemporaryDirectory() as directory:
            provisioner.stream_download(
                "https://example.invalid/asset", Path(directory) / "download",
                expected_size=len(data), expected_sha256=self.sha(data),
                opener=opener, network_timeout=3.25,
            )
        opener.assert_called_once_with("https://example.invalid/asset", timeout=3.25)

    def test_stream_download_does_not_misclassify_body_io_as_timer_failure(self):
        class FailingResponse(FakeResponse):
            def read(self, size=-1):
                raise OSError("fixture network read failure")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "download"
            with self.assertRaisesRegex(
                provisioner.ProvisionError, "^download failed$"
            ):
                provisioner.stream_download(
                    "https://example.invalid/asset",
                    output,
                    expected_size=1,
                    expected_sha256=self.sha(b"x"),
                    opener=lambda unused, **kwargs: FailingResponse(b"", 1),
                )
            self.assertFalse(output.exists())

    def test_stream_download_enforces_monotonic_total_deadline(self):
        data = b"abcdef"
        clock = [100.0]

        class SlowResponse(FakeResponse):
            def read(self, size=-1):
                clock[0] += 0.3
                return super().read(size)

        response = SlowResponse(data, len(data))
        opener = mock.Mock(return_value=response)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "download"
            with (
                mock.patch.object(provisioner.time, "monotonic", side_effect=lambda: clock[0]),
                self.assertRaisesRegex(provisioner.ProvisionError, "deadline"),
            ):
                provisioner.stream_download(
                    "https://example.invalid/asset",
                    output,
                    expected_size=len(data),
                    expected_sha256=self.sha(data),
                    opener=opener,
                    chunk_size=2,
                    network_timeout=3.25,
                    total_timeout=0.5,
                )
            self.assertFalse(output.exists())
        opener.assert_called_once_with("https://example.invalid/asset", timeout=0.5)
        self.assertEqual(response.read_sizes, [2, 2])

    def test_stream_download_interrupts_one_blocking_read_at_total_deadline(self):
        data = b"payload"

        class BlockingResponse(FakeResponse):
            def read(self, size=-1):
                time.sleep(0.2)
                return super().read(size)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "download"
            started = time.monotonic()
            with self.assertRaisesRegex(provisioner.ProvisionError, "deadline"):
                provisioner.stream_download(
                    "https://example.invalid/asset",
                    output,
                    expected_size=len(data),
                    expected_sha256=self.sha(data),
                    opener=mock.Mock(return_value=BlockingResponse(data, len(data))),
                    total_timeout=0.05,
                )
            elapsed = time.monotonic() - started
            # Hosted CI runners (macOS arm64) have observed ~0.17s of
            # scheduling jitter on top of the 0.05s deadline; the intent
            # is that the interrupt fires within a small multiple of the
            # total timeout, not a fixed sub-second wall time.
            self.assertLess(elapsed, 0.5)
            self.assertFalse(output.exists())

    def test_stream_download_preserves_preexisting_destination(self):
        data = b"trusted operator bytes"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "download"
            output.write_bytes(data)
            with self.assertRaises(provisioner.ProvisionError):
                provisioner.stream_download(
                    "https://example.invalid/asset", output,
                    expected_size=1, expected_sha256=self.sha(b"x"),
                    opener=lambda unused, **kwargs: FakeResponse(b"x", 1),
                )
            self.assertEqual(output.read_bytes(), data)

    def test_safe_members_allows_only_regular_files_and_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            tarball = Path(directory) / "fixture.tar"
            with tarfile.open(tarball, "w") as archive:
                item = tarfile.TarInfo("pkg")
                item.type = tarfile.DIRTYPE
                archive.addfile(item)
                self.add_bytes(archive, "pkg/file", b"data")
            with tarfile.open(tarball, "r") as archive:
                members = provisioner.safe_members(
                    archive, expected_extracted_size=4, expected_top_level="pkg"
                )
            self.assertEqual([member.name for member in members], ["pkg", "pkg/file"])

    def test_safe_members_uses_exact_extracted_size_not_compressed_tarball_size(self):
        with tempfile.TemporaryDirectory() as directory:
            tarball = Path(directory) / "compressible.tar.gz"
            payload = b"A" * (1024 * 1024)
            with tarfile.open(tarball, "w:gz") as archive:
                item = tarfile.TarInfo("pkg")
                item.type = tarfile.DIRTYPE
                archive.addfile(item)
                self.add_bytes(archive, "pkg/payload", payload)
            self.assertLess(tarball.stat().st_size, len(payload))

            with tarfile.open(tarball, "r:gz") as archive:
                members = provisioner.safe_members(
                    archive,
                    expected_extracted_size=len(payload),
                    expected_top_level="pkg",
                )
            self.assertEqual(sum(member.size for member in members if member.isreg()), len(payload))

            with tarfile.open(tarball, "r:gz") as archive, self.assertRaises(provisioner.ProvisionError):
                provisioner.safe_members(
                    archive,
                    expected_extracted_size=len(payload) - 1,
                    expected_top_level="pkg",
                )

    def test_safe_members_rejects_unsafe_names_and_special_entries(self):
        unsafe = (
            ("/absolute", tarfile.REGTYPE, ""),
            ("../escape", tarfile.REGTYPE, ""),
            ("pkg/../escape", tarfile.REGTYPE, ""),
            (".", tarfile.DIRTYPE, ""),
            ("pkg//empty", tarfile.REGTYPE, ""),
            ("pkg/./dot", tarfile.REGTYPE, ""),
            ("pkg/device", tarfile.CHRTYPE, ""),
            ("pkg/fifo", tarfile.FIFOTYPE, ""),
            ("pkg/link", tarfile.SYMTYPE, "outside"),
            ("pkg/hard", tarfile.LNKTYPE, "pkg/file"),
        )
        for name, kind, linkname in unsafe:
            with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as directory:
                tarball = Path(directory) / "fixture.tar"
                with tarfile.open(tarball, "w") as archive:
                    self.add_bytes(archive, name, kind=kind, linkname=linkname)
                with tarfile.open(tarball, "r") as archive, self.assertRaises(provisioner.ProvisionError):
                    provisioner.safe_members(archive, expected_extracted_size=0)

    def test_safe_members_rejects_duplicate_resolved_path_wrong_top_level_and_bombs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = root / "duplicate.tar"
            with tarfile.open(duplicate, "w") as archive:
                self.add_bytes(archive, "pkg/file", b"a")
                self.add_bytes(archive, "pkg/file", b"b")
            with tarfile.open(duplicate) as archive, self.assertRaises(provisioner.ProvisionError):
                provisioner.safe_members(archive, expected_extracted_size=2)

            multiple = root / "multiple.tar"
            with tarfile.open(multiple, "w") as archive:
                self.add_bytes(archive, "one/file", b"a")
                self.add_bytes(archive, "two/file", b"b")
            with tarfile.open(multiple) as archive, self.assertRaises(provisioner.ProvisionError):
                provisioner.safe_members(archive, expected_extracted_size=2, expected_top_level="one")

            bomb = root / "bomb.tar"
            with tarfile.open(bomb, "w") as archive:
                self.add_bytes(archive, "pkg/file", b"0123456789")
            with tarfile.open(bomb) as archive, self.assertRaises(provisioner.ProvisionError):
                provisioner.safe_members(archive, expected_extracted_size=5)
            with tarfile.open(bomb) as archive, self.assertRaises(provisioner.ProvisionError):
                provisioner.safe_members(archive, expected_extracted_size=10, max_members=0)

    def test_safe_members_rejects_case_and_unicode_alias_collisions(self):
        aliases = (
            ("pkg/Dir", "pkg/dir/file"),
            ("pkg/caf\N{LATIN SMALL LETTER E WITH ACUTE}", "pkg/cafe\N{COMBINING ACUTE ACCENT}/file"),
        )
        for first, second in aliases:
            with self.subTest(first=first, second=second), tempfile.TemporaryDirectory() as directory:
                tarball = Path(directory) / "aliases.tar"
                with tarfile.open(tarball, "w") as archive:
                    self.add_bytes(archive, first, kind=tarfile.DIRTYPE)
                    self.add_bytes(archive, second, b"payload")
                with tarfile.open(tarball) as archive, self.assertRaises(provisioner.ProvisionError):
                    provisioner.safe_members(archive, expected_extracted_size=len(b"payload"))

    def test_manual_extraction_refuses_existing_resolved_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tarball = root / "fixture.tar"
            with tarfile.open(tarball, "w") as archive:
                self.add_bytes(archive, "pkg/link/file", b"payload")
            destination = root / "destination"
            destination.mkdir()
            (destination / "pkg").mkdir()
            os.symlink(root, destination / "pkg" / "link")
            with tarfile.open(tarball) as archive:
                members = provisioner.safe_members(archive, expected_extracted_size=len(b"payload"))
                with self.assertRaises(provisioner.ProvisionError):
                    provisioner._extract_members(archive, members, destination)

    def test_manual_extraction_handles_partial_os_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tarball = root / "fixture.tar"
            with tarfile.open(tarball, "w") as archive:
                self.add_bytes(archive, "pkg/file", b"payload")
            destination = root / "destination"
            real_write = os.write

            def partial_write(fd, data):
                return real_write(fd, data[:1])

            with tarfile.open(tarball) as archive:
                members = provisioner.safe_members(archive, expected_extracted_size=len(b"payload"))
                with mock.patch.object(provisioner.os, "write", side_effect=partial_write):
                    provisioner._extract_members(archive, members, destination)
            self.assertEqual((destination / "pkg/file").read_bytes(), b"payload")

    def test_verify_sha256sums_accepts_one_dot_prefix_and_verifies_all_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = self.package_files()
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            records = provisioner.verify_sha256sums(
                root, expected_manifest_sha256=self.sha(files["SHA256SUMS"])
            )
            self.assertEqual(set(records), {"MANIFEST.sha256", "payload.txt", "plugin/hermes/jackal_hermes"})

    def test_verify_sha256sums_rejects_oversized_manifest_before_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "SHA256SUMS"
            with manifest.open("wb") as handle:
                handle.truncate(provisioner.MAX_RUNTIME_MANIFEST_BYTES + 1)

            with (
                mock.patch.object(provisioner.os, "read", wraps=provisioner.os.read) as read,
                self.assertRaises(provisioner.ProvisionError),
            ):
                provisioner.verify_sha256sums(root)

            read.assert_not_called()

    def test_verify_sha256sums_bounds_record_count_depth_and_utf8_path_bytes(self):
        digest = self.sha(b"payload")
        cases = (
            ("records", f"{digest}  ./a\n{digest}  ./b\n"),
            ("depth", f"{digest}  ./nested/payload\n"),
            ("path-bytes", f"{digest}  ./é.txt\n"),
        )
        for case, manifest in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "SHA256SUMS").write_text(manifest, encoding="utf-8")
                patches = {
                    "records": mock.patch.object(provisioner, "MAX_RUNTIME_RECORDS", 1),
                    "depth": mock.patch.object(provisioner, "MAX_RUNTIME_DEPTH", 1),
                    "path-bytes": mock.patch.object(
                        provisioner, "MAX_RUNTIME_PATH_BYTES", 5
                    ),
                }
                with patches[case], self.assertRaises(provisioner.ProvisionError):
                    provisioner.verify_sha256sums(root)

    def test_verify_sha256sums_rejects_oversized_named_file_before_hashing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "payload"
            with payload.open("wb") as handle:
                handle.truncate(provisioner.MAX_RUNTIME_FILE_BYTES + 1)
            (root / "SHA256SUMS").write_text(
                f"{self.sha(b'expected')}  ./payload\n", encoding="utf-8"
            )

            with (
                mock.patch.object(provisioner, "_hash_fd", wraps=provisioner._hash_fd) as hash_fd,
                self.assertRaises(provisioner.ProvisionError),
            ):
                provisioner.verify_sha256sums(root)

            hash_fd.assert_not_called()

    def test_verify_sha256sums_bounds_aggregate_named_file_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = b"a" * 8
            second = b"b" * 8
            (root / "first").write_bytes(first)
            (root / "second").write_bytes(second)
            manifest = "".join(
                f"{self.sha(data)}  ./{name}\n"
                for name, data in (("first", first), ("second", second))
            )
            (root / "SHA256SUMS").write_text(manifest, encoding="utf-8")

            with (
                mock.patch.object(provisioner, "MAX_RUNTIME_FILE_BYTES", 8),
                mock.patch.object(provisioner, "MAX_RUNTIME_TOTAL_BYTES", 12),
                self.assertRaises(provisioner.ProvisionError),
            ):
                provisioner.verify_sha256sums(root)

    def test_runtime_inventory_entry_limit_refuses_before_named_file_hashing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"payload"
            (root / "payload").write_bytes(payload)
            (root / "unlisted-1").write_bytes(b"extra")
            (root / "unlisted-2").write_bytes(b"extra")
            (root / "SHA256SUMS").write_text(
                f"{self.sha(payload)}  ./payload\n", encoding="utf-8"
            )

            with (
                mock.patch.object(provisioner, "MAX_RUNTIME_ENTRIES", 2),
                mock.patch.object(provisioner, "_hash_fd", wraps=provisioner._hash_fd) as hash_fd,
                self.assertRaises(provisioner.ProvisionError),
            ):
                provisioner.verify_sha256sums(root)

            hash_fd.assert_not_called()

    def test_verify_sha256sums_rejects_unlisted_files_and_special_entries(self):
        for kind in ("file", "fifo"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                files = self.package_files()
                for name, data in files.items():
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                extra = root / "unlisted"
                extra.write_bytes(b"hidden") if kind == "file" else os.mkfifo(extra)
                with self.assertRaises(provisioner.ProvisionError):
                    provisioner.verify_sha256sums(
                        root, expected_manifest_sha256=self.sha(files["SHA256SUMS"])
                    )

    def test_verify_sha256sums_rejects_unlisted_empty_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = self.package_files()
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            (root / "unlisted-empty-directory").mkdir()
            with self.assertRaises(provisioner.ProvisionError):
                provisioner.verify_sha256sums(
                    root, expected_manifest_sha256=self.sha(files["SHA256SUMS"])
                )

    def test_verify_sha256sums_rejects_malformed_duplicate_or_unsafe_lines(self):
        digest = self.sha(b"x")
        bad_manifests = (
            f"{digest.upper()}  ./x\n",
            f"{digest} ./x\n",
            f"{digest}  x\n{digest}  ./x\n",
            f"{digest}  ../x\n",
            f"{digest}  .//x\n",
            f"{digest}  ./nested/../x\n",
            f"{digest}  ././x\n",
            f"{digest}  /x\n",
        )
        for manifest in bad_manifests:
            with self.subTest(manifest=manifest), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "x").write_bytes(b"x")
                (root / "SHA256SUMS").write_text(manifest, encoding="utf-8")
                with self.assertRaises(provisioner.ProvisionError):
                    provisioner.verify_sha256sums(root)

    def test_verify_sha256sums_rejects_case_and_unicode_directory_aliases(self):
        digest = self.sha(b"payload")
        alias_sets = (
            ("Dir/a", "dir/b"),
            ("cafe\N{COMBINING ACUTE ACCENT}/a", "caf\N{LATIN SMALL LETTER E WITH ACUTE}/b"),
        )
        for aliases in alias_sets:
            lines = "".join(f"{digest}  ./{name}\n" for name in sorted(aliases))
            with self.subTest(aliases=aliases), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "SHA256SUMS").write_text(lines, encoding="utf-8")
                with self.assertRaises(provisioner.ProvisionError):
                    provisioner.verify_sha256sums(root)

    def test_verify_sha256sums_refuses_symlink_nonregular_and_fifo_without_blocking(self):
        kinds = ("symlink", "directory", "fifo")
        for kind in kinds:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / "payload"
                if kind == "symlink":
                    real = root / "real"
                    real.write_bytes(b"payload")
                    os.symlink(real, target)
                elif kind == "directory":
                    target.mkdir()
                else:
                    os.mkfifo(target)
                (root / "SHA256SUMS").write_text(f"{self.sha(b'payload')}  ./payload\n", encoding="utf-8")
                program = (
                    "import sys; from pathlib import Path; "
                    "from plugins.jackel.scripts.provision_runtime import ProvisionError, verify_sha256sums; "
                    "\ntry: verify_sha256sums(Path(sys.argv[1]))"
                    "\nexcept ProvisionError: raise SystemExit(0)"
                    "\nraise SystemExit(1)"
                )
                result = subprocess.run(
                    [os.sys.executable, "-B", "-c", program, str(root)],
                    cwd=Path(__file__).resolve().parents[2],
                    capture_output=True, timeout=1.0,
                )
                self.assertEqual(result.returncode, 0)

    def test_verify_sha256sums_refuses_path_replacement_after_hashing_open_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "runtime"
            root.mkdir()
            original = b"original"
            replacement = b"replacement"
            payload = root / "payload"
            payload.write_bytes(original)
            other = base / "other"
            other.write_bytes(replacement)
            (root / "SHA256SUMS").write_text(f"{self.sha(original)}  ./payload\n", encoding="utf-8")
            real_hash = provisioner._hash_fd

            def replace_after_hash(fd, *, byte_limit):
                result = real_hash(fd, byte_limit=byte_limit)
                payload.unlink()
                os.symlink(other, payload)
                return result

            with mock.patch.object(provisioner, "_hash_fd", side_effect=replace_after_hash):
                with self.assertRaises(provisioner.ProvisionError):
                    provisioner.verify_sha256sums(root)

    def test_validate_runtime_requires_manifest_checksums_executable_and_identity_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = self.package_files()
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            launcher = root / "plugin/hermes/jackal_hermes"
            launcher.chmod(0o755)
            tree_digest = self.sha(files["SHA256SUMS"])
            provisioner.validate_runtime(root, timeout=1.0, expected_tree_sha256=tree_digest)

            launcher.chmod(0o644)
            with self.assertRaises(provisioner.ProvisionError):
                provisioner.validate_runtime(root, timeout=1.0, expected_tree_sha256=tree_digest)

            launcher.chmod(0o755)
            launcher.write_bytes(self.package_files(marker=False)["plugin/hermes/jackal_hermes"])
            checksums = root / "SHA256SUMS"
            lines = checksums.read_text().splitlines()
            lines = [
                f"{self.sha(launcher.read_bytes())}  ./plugin/hermes/jackal_hermes"
                if line.endswith("./plugin/hermes/jackal_hermes") else line for line in lines
            ]
            checksums.write_text("\n".join(lines) + "\n")
            with self.assertRaises(provisioner.ProvisionError):
                provisioner.validate_runtime(
                    root, timeout=1.0,
                    expected_tree_sha256=self.sha(checksums.read_bytes()),
                )

    def test_validate_runtime_uses_bounded_timeout_and_requires_zero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = self.package_files()
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            (root / "plugin/hermes/jackal_hermes").chmod(0o755)
            runner = mock.Mock(return_value=subprocess.CompletedProcess([], 1, "plugin_hermes.identity_match=true\n", ""))
            with self.assertRaises(provisioner.ProvisionError):
                provisioner.validate_runtime(
                    root, timeout=0.25,
                    expected_tree_sha256=self.sha(files["SHA256SUMS"]),
                    selftest_runner=runner,
                )
            self.assertEqual(runner.call_args.kwargs["timeout"], 0.25)

    def test_private_runtime_snapshot_is_exact_independent_and_owned(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "runtime"
            files = self.write_runtime_fixture(source)
            tree_digest = self.sha(files["SHA256SUMS"])

            snapshot = provisioner.create_runtime_snapshot(
                source,
                expected_tree_sha256=tree_digest,
                timeout=1.0,
                temporary_parent=base / "snapshots",
            )
            snapshot_root = snapshot.root

            self.assertNotEqual(snapshot_root, source)
            self.assertEqual(snapshot_root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(
                (snapshot_root / "payload.txt").read_bytes(), b"payload\n"
            )
            self.assertNotEqual(
                (snapshot_root / "payload.txt").stat().st_ino,
                (source / "payload.txt").stat().st_ino,
            )
            self.assertEqual(
                (snapshot_root / "plugin/hermes/jackal_hermes").stat().st_mode & 0o777,
                0o700,
            )

            (source / "payload.txt").write_bytes(b"mutated original\n")
            (source / "plugin/hermes/jackal_hermes").write_text(
                "#!/bin/sh\necho forged\n", encoding="utf-8",
            )
            self.assertEqual(
                (snapshot_root / "payload.txt").read_bytes(), b"payload\n"
            )
            self.assertIn(
                "plugin_hermes.identity_match=true",
                (snapshot_root / "plugin/hermes/jackal_hermes").read_text(),
            )

            snapshot.close()
            self.assertFalse(snapshot_root.exists())

    def test_runtime_snapshot_cleanup_failure_remains_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            cleanup = mock.Mock(side_effect=(OSError("fixture cleanup failure"), None))
            owner = types.SimpleNamespace(name=directory, cleanup=cleanup)
            snapshot = provisioner.RuntimeSnapshot(owner)

            with self.assertRaises(OSError):
                snapshot.close()
            self.assertFalse(snapshot._closed)

            snapshot.close()
            self.assertTrue(snapshot._closed)
            self.assertEqual(cleanup.call_count, 2)

    def test_runtime_snapshot_preflights_file_size_against_remaining_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            destination = base / "destination"
            source.mkdir()
            destination.mkdir()
            (source / "payload.txt").write_bytes(b"12345")
            source_fd = os.open(source, provisioner._directory_flags())
            destination_fd = os.open(destination, provisioner._directory_flags())
            try:
                with (
                    mock.patch.object(
                        provisioner,
                        "_copy_file_bytes",
                        side_effect=AssertionError("oversized file must not be copied"),
                    ),
                    self.assertRaisesRegex(provisioner.ProvisionError, "byte limit"),
                ):
                    provisioner._copy_runtime_file(
                        source_fd,
                        destination_fd,
                        "payload.txt",
                        self.sha(b"12345"),
                        byte_limit=4,
                    )
            finally:
                os.close(destination_fd)
                os.close(source_fd)
            self.assertFalse((destination / "payload.txt").exists())

    def test_runtime_snapshot_growth_never_writes_past_remaining_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            destination = base / "destination"
            source.mkdir()
            destination.mkdir()
            payload = source / "payload.txt"
            payload.write_bytes(b"123")
            source_fd = os.open(source, provisioner._directory_flags())
            destination_fd = os.open(destination, provisioner._directory_flags())
            original_copy = provisioner._copy_file_bytes

            def grow_after_preflight(*args, **kwargs):
                payload.write_bytes(b"1234567890")
                return original_copy(*args, **kwargs)

            try:
                with (
                    mock.patch.object(
                        provisioner,
                        "_copy_file_bytes",
                        side_effect=grow_after_preflight,
                    ),
                    self.assertRaisesRegex(provisioner.ProvisionError, "byte limit"),
                ):
                    provisioner._copy_runtime_file(
                        source_fd,
                        destination_fd,
                        "payload.txt",
                        self.sha(b"123"),
                        byte_limit=4,
                    )
            finally:
                os.close(destination_fd)
                os.close(source_fd)
            copied = destination / "payload.txt"
            self.assertTrue(copied.exists())
            self.assertLessEqual(copied.stat().st_size, 4)

    def test_runtime_snapshot_rejects_unsafe_partial_and_extra_inputs_without_leaks(self):
        cases = ("symlink", "fifo", "extra", "partial")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                source = base / "runtime"
                files = self.write_runtime_fixture(source)
                if case == "symlink":
                    target = base / "external"
                    target.write_bytes(b"payload\n")
                    (source / "payload.txt").unlink()
                    os.symlink(target, source / "payload.txt")
                elif case == "fifo":
                    os.mkfifo(source / "unlisted-fifo")
                elif case == "extra":
                    (source / "unlisted").write_bytes(b"extra")
                else:
                    (source / "payload.txt").unlink()
                parent = base / "snapshots"
                with self.assertRaises(provisioner.ProvisionError):
                    provisioner.create_runtime_snapshot(
                        source,
                        expected_tree_sha256=self.sha(files["SHA256SUMS"]),
                        timeout=1.0,
                        temporary_parent=parent,
                    )
                self.assertFalse(parent.exists() and any(parent.iterdir()))

    def test_runtime_snapshot_rejects_coordinated_aba_during_copy_and_cleans(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "runtime"
            files = self.write_runtime_fixture(source)
            payload = source / "payload.txt"
            preserved_inode = base / "preserved-payload-inode"
            os.link(payload, preserved_inode)
            parent = base / "snapshots"
            real_copy = provisioner._copy_file_bytes
            changed = False

            def aba_after_copy(source_fd, destination_fd, relative, *, byte_limit):
                nonlocal changed
                result = real_copy(
                    source_fd,
                    destination_fd,
                    relative,
                    byte_limit=byte_limit,
                )
                if relative == "payload.txt" and not changed:
                    changed = True
                    payload.unlink()
                    os.link(preserved_inode, payload)
                return result

            with (
                mock.patch.object(
                    provisioner, "_copy_file_bytes", side_effect=aba_after_copy
                ),
                self.assertRaises(provisioner.ProvisionError),
            ):
                provisioner.create_runtime_snapshot(
                    source,
                    expected_tree_sha256=self.sha(files["SHA256SUMS"]),
                    timeout=1.0,
                    temporary_parent=parent,
                )
            self.assertTrue(changed)
            self.assertFalse(parent.exists() and any(parent.iterdir()))

    def test_selftest_starts_new_session_and_caps_combined_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            launcher = b"#!/bin/sh\necho plugin_hermes.identity_match=true\npython3 -c 'print(\"x\" * 100000)'\n"
            files = self.package_files(launcher=launcher)
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            (root / "plugin/hermes/jackal_hermes").chmod(0o755)
            with mock.patch.object(provisioner.subprocess, "Popen", wraps=subprocess.Popen) as factory:
                with self.assertRaises(provisioner.ProvisionError):
                    provisioner.validate_runtime(
                        root, timeout=1.0, output_limit=128,
                        expected_tree_sha256=self.sha(files["SHA256SUMS"]),
                    )
            self.assertTrue(factory.call_args.kwargs["start_new_session"])

    def test_selftest_timeout_terminates_descendant_process_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child_pid = root / "child.pid"
            launcher = (
                "#!/bin/sh\n"
                "sleep 30 &\n"
                f"echo $! > '{child_pid}'\n"
                "sleep 30\n"
            ).encode()
            files = self.package_files(launcher=launcher)
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            (root / "plugin/hermes/jackal_hermes").chmod(0o755)
            with self.assertRaises(provisioner.ProvisionError):
                provisioner.validate_runtime(
                    root, timeout=0.75,
                    expected_tree_sha256=self.sha(files["SHA256SUMS"]),
                )
            pid = int(child_pid.read_text())
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                state = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "state="],
                    capture_output=True, text=True, check=False,
                ).stdout.strip()
                if not state or state.startswith("Z"):
                    break
                time.sleep(0.02)
            self.assertTrue(not state or state.startswith("Z"), f"descendant still alive: {state}")

    def test_successful_selftest_cleans_background_descendant_with_closed_pipes(self):
        with tempfile.TemporaryDirectory() as directory:
            container = Path(directory)
            root = container / "runtime"
            child_pid = container / "child.pid"
            launcher = (
                "#!/bin/sh\n"
                "sleep 30 </dev/null >/dev/null 2>&1 &\n"
                f"echo $! > '{child_pid}'\n"
                "echo plugin_hermes.identity_match=true\n"
                "exit 0\n"
            ).encode()
            files = self.package_files(launcher=launcher)
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            (root / "plugin/hermes/jackal_hermes").chmod(0o755)

            provisioner.validate_runtime(
                root, timeout=1.0,
                expected_tree_sha256=self.sha(files["SHA256SUMS"]),
            )

            pid = int(child_pid.read_text())
            state = subprocess.run(
                ["ps", "-p", str(pid), "-o", "state="],
                capture_output=True, text=True, check=False,
            ).stdout.strip()
            self.assertTrue(not state or state.startswith("Z"), f"descendant still alive: {state}")

    def test_selftest_cleanup_precedes_reap_and_uses_wnowait_observation(self):
        events = []
        captured = {}
        waitid_calls = []

        def process_factory(*args, **kwargs):
            process = subprocess.Popen(*args, **kwargs)
            captured["process"] = process
            real_wait = process.wait

            def guarded_wait(*wait_args, **wait_kwargs):
                events.append("reap-boundary")
                return real_wait(*wait_args, **wait_kwargs)

            process.wait = guarded_wait
            return process

        def observe_without_reaping(idtype, pid, flags):
            waitid_calls.append((idtype, pid, flags))
            return os.waitid(idtype, pid, flags)

        def signal_anchored_group(process_group, sent_signal):
            self.assertNotIn("reap-boundary", events)
            self.assertIsNone(captured["process"].returncode)
            events.append(f"signal-anchored-group:{sent_signal}")
            raise ProcessLookupError

        result = provisioner._run_selftest(
            ["/bin/sh", "-c", "echo plugin_hermes.identity_match=true"],
            timeout=1.0,
            output_limit=1024,
            popen_factory=process_factory,
            waitid_func=observe_without_reaping,
            kill_group=signal_anchored_group,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(events, ["reap-boundary"])
        self.assertTrue(waitid_calls)
        self.assertTrue(all(flags & os.WNOWAIT for unused_type, unused_pid, flags in waitid_calls))

    def test_selftest_selector_allocation_failure_cleans_spawned_process(self):
        process = mock.Mock(pid=424204)
        process.stdout = io.BytesIO()
        process.stderr = io.BytesIO()
        with (
            mock.patch.object(
                provisioner.selectors,
                "DefaultSelector",
                side_effect=OSError("descriptor exhaustion"),
            ),
            mock.patch.object(provisioner, "_terminate_process_group") as terminate,
            self.assertRaisesRegex(provisioner.ProvisionError, "monitor setup"),
        ):
            provisioner._run_selftest(
                ["/absolute/runtime", "selftest"],
                timeout=1.0,
                output_limit=1024,
                popen_factory=mock.Mock(return_value=process),
            )

        terminate.assert_called_once_with(process, provisioner.os.killpg)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)

    def test_process_group_observer_selector_failure_cleans_observer(self):
        observer = mock.Mock()
        observer.stdout = io.BytesIO()
        observer.poll.return_value = None
        observer.wait.return_value = -signal.SIGTERM
        with (
            mock.patch.object(provisioner.subprocess, "Popen", return_value=observer),
            mock.patch.object(
                provisioner.selectors,
                "DefaultSelector",
                side_effect=OSError("descriptor exhaustion"),
            ),
            self.assertRaisesRegex(provisioner.ProvisionError, "observer setup"),
        ):
            provisioner._exited_group_has_only_zombie_members(424205)

        observer.terminate.assert_called_once_with()
        observer.wait.assert_called_once_with(timeout=0.1)
        self.assertTrue(observer.stdout.closed)

    def test_process_group_observer_accepts_leader_plus_only_zombie_members(self):
        self.assertTrue(
            provisioner._group_observation_is_quiescent(
                b"424208 Z\n424209 Z+\n424210 Z\n", 424208
            )
        )
        self.assertTrue(
            hasattr(provisioner, "_exited_group_has_only_zombie_members")
        )
        self.assertFalse(
            hasattr(provisioner, "_exited_group_has_only_zombie_leader")
        )
        self.assertFalse(
            provisioner._group_observation_is_quiescent(
                b"424208 Z\n424209 S\n", 424208
            )
        )
        self.assertFalse(
            provisioner._group_observation_is_quiescent(b"424209 Z\n", 424208)
        )

    def test_process_group_observer_cleanup_timeout_is_named(self):
        observer = mock.Mock()
        observer.stdout = io.BytesIO()
        observer.poll.return_value = None
        observer.wait.side_effect = (
            subprocess.TimeoutExpired(["ps"], 0.1),
            subprocess.TimeoutExpired(["ps"], 0.1),
        )
        with (
            mock.patch.object(provisioner.subprocess, "Popen", return_value=observer),
            mock.patch.object(
                provisioner.selectors,
                "DefaultSelector",
                side_effect=OSError("descriptor exhaustion"),
            ),
            self.assertRaisesRegex(provisioner.ProvisionError, "did not exit"),
        ):
            provisioner._exited_group_has_only_zombie_members(424207)

        observer.terminate.assert_called_once_with()
        observer.kill.assert_called_once_with()
        self.assertTrue(observer.stdout.closed)

    def test_selftest_group_permission_denial_is_a_named_failure(self):
        def deny(unused_group, unused_signal):
            raise OSError(errno.EPERM, "not permitted")

        with self.assertRaisesRegex(provisioner.ProvisionError, "permission denied"):
            provisioner._process_group_exists(424200, deny)
        with self.assertRaisesRegex(provisioner.ProvisionError, "permission denied"):
            provisioner._cleanup_process_group(424201, deny)

        signals = []

        def deny_kill(unused_group, sent_signal):
            signals.append(sent_signal)
            if sent_signal == signal.SIGKILL:
                raise OSError(errno.EPERM, "not permitted")

        with (
            mock.patch.object(provisioner.time, "monotonic", side_effect=(0.0, 1.0)),
            self.assertRaisesRegex(provisioner.ProvisionError, "permission denied"),
        ):
            provisioner._cleanup_process_group(424202, deny_kill)
        self.assertEqual(signals, [signal.SIGTERM, signal.SIGKILL])

        cleanup = mock.Mock()
        with mock.patch.object(
            provisioner, "_exited_group_has_only_zombie_members", return_value=True
        ) as observe_quiescent:
            provisioner._cleanup_completed_process_group(424203, cleanup, deny)
        observe_quiescent.assert_called_once_with(424203)
        cleanup.assert_not_called()

    def test_selftest_transient_eperm_requires_positive_bounded_quiescence(self):
        signals = []

        def transient_after_term(unused_group, sent_signal):
            signals.append(sent_signal)
            if sent_signal == 0:
                raise OSError(errno.EPERM, "transient zombie transition")

        quiescent = mock.Mock(side_effect=(False, False, True))
        provisioner._cleanup_process_group(
            424210,
            transient_after_term,
            quiescent_check=quiescent,
        )
        self.assertEqual(signals, [signal.SIGTERM, 0])
        self.assertEqual(quiescent.call_count, 3)

        persistent = mock.Mock(return_value=False)
        with self.assertRaisesRegex(provisioner.ProvisionError, "permission denied"):
            provisioner._cleanup_process_group(
                424211,
                transient_after_term,
                quiescent_check=persistent,
            )
        self.assertGreaterEqual(persistent.call_count, 2)

    def test_failed_quiescence_observer_cannot_prevent_group_cleanup(self):
        cleanup = mock.Mock()
        deny = mock.Mock()
        with mock.patch.object(
            provisioner,
            "_exited_group_has_only_zombie_members",
            side_effect=provisioner.ProvisionError("observer unavailable"),
        ):
            provisioner._cleanup_completed_process_group(424206, cleanup, deny)

        cleanup.assert_called_once()
        process_group, kill_group = cleanup.call_args.args
        self.assertEqual(process_group, 424206)
        self.assertIs(kill_group, deny)
        self.assertFalse(cleanup.call_args.kwargs["quiescent_check"]())

    def test_exact_metadata_is_bounded_canonical_and_duplicate_safe(self):
        expected = provisioner._package_metadata(
            epoch="v1.7.0",
            asset=provisioner.ASSET,
            size=17,
            digest=self.sha(b"package"),
        )
        canonical = (
            json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / ".jackal-package.json"

            metadata.write_bytes(b" " * (16 * 1024 + 1))
            with (
                mock.patch.object(
                    provisioner.json,
                    "loads",
                    side_effect=AssertionError("oversized metadata must not be parsed"),
                ),
                self.assertRaisesRegex(provisioner.ProvisionError, "metadata"),
            ):
                provisioner._load_exact_metadata(metadata, expected)

            duplicate = b'{"schema":"forged",' + canonical[1:]
            metadata.write_bytes(duplicate)
            with self.assertRaisesRegex(provisioner.ProvisionError, "metadata"):
                provisioner._load_exact_metadata(metadata, expected)

            metadata.write_text(json.dumps(expected, indent=2) + "\n")
            with self.assertRaisesRegex(provisioner.ProvisionError, "metadata"):
                provisioner._load_exact_metadata(metadata, expected)

            metadata.write_bytes(canonical)
            provisioner._load_exact_metadata(metadata, expected)

    def test_exact_metadata_rejects_path_replacement_and_coordinated_aba(self):
        expected = provisioner._package_metadata(
            epoch="v1.7.0",
            asset=provisioner.ASSET,
            size=17,
            digest=self.sha(b"package"),
        )
        canonical = (
            json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        real_read_fd = provisioner._read_fd

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / ".jackal-package.json"
            replacement = root / "replacement.json"
            metadata.write_bytes(canonical)
            replacement.write_bytes(canonical)

            def replace_after_read(fd, *, byte_limit):
                data = real_read_fd(fd, byte_limit=byte_limit)
                os.replace(replacement, metadata)
                return data

            with (
                mock.patch.object(provisioner, "_read_fd", side_effect=replace_after_read),
                self.assertRaisesRegex(provisioner.ProvisionError, "metadata"),
            ):
                provisioner._load_exact_metadata(metadata, expected)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / ".jackal-package.json"
            parked = root / "parked.json"
            replacement = root / "replacement.json"
            metadata.write_bytes(canonical)
            replacement.write_bytes(canonical)

            def aba_after_read(fd, *, byte_limit):
                data = real_read_fd(fd, byte_limit=byte_limit)
                before = root.stat()
                os.replace(metadata, parked)
                os.replace(replacement, metadata)
                os.replace(metadata, replacement)
                os.replace(parked, metadata)
                os.utime(
                    root,
                    ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000),
                )
                return data

            with (
                mock.patch.object(provisioner, "_read_fd", side_effect=aba_after_read),
                self.assertRaisesRegex(provisioner.ProvisionError, "metadata"),
            ):
                provisioner._load_exact_metadata(metadata, expected)

    def test_provision_offline_installs_metadata_and_locator_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tarball = self.make_tarball(root)
            result, target, locator = self.provision_fixture(root, tarball)
            digest = self.sha(tarball.read_bytes())
            self.assertEqual(result, target)
            self.assertTrue((target / "plugin/hermes/jackal_hermes").exists())
            expected = {
                "schema": "jackal-runtime-package-v1",
                "epoch": provisioner.EPOCH,
                "asset": provisioner.ASSET,
                "package_size": tarball.stat().st_size,
                "package_sha256": digest,
            }
            self.assertEqual(json.loads((target / ".jackal-package.json").read_text()), expected)
            self.assertEqual(
                json.loads(locator.read_text()),
                {
                    "schema": "jackal-codex-plugin-runtime-v1",
                    "epoch": provisioner.EPOCH,
                    "runtime_path": str(target),
                    "package_size": tarball.stat().st_size,
                    "package_sha256": digest,
                },
            )
            self.assertFalse(any("stage" in path.name or "download" in path.name for path in target.parent.iterdir()))

    def test_provision_rejects_bad_outer_digest_before_tar_open_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tarball = self.make_tarball(root)
            target = root / "support/runtimes/v1.7.0"
            with mock.patch.object(tarfile, "open", side_effect=AssertionError("must not open tar")):
                with self.assertRaises(provisioner.ProvisionError):
                    provisioner.provision(
                        tarball=tarball, runtime_target=target,
                        locator_path=root / "locator.json",
                        expected_size=tarball.stat().st_size,
                        expected_sha256="0" * 64,
                        expected_top_level="jackal-v1.7.0-macos-arm64",
                        system="Darwin", machine="arm64",
                    )
            self.assertFalse(target.exists())
            self.assertFalse(target.parent.exists() and any(target.parent.iterdir()))

    def test_provision_requires_exactly_expected_top_level(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tarball = self.make_tarball(root, top="wrong")
            with self.assertRaises(provisioner.ProvisionError):
                self.provision_fixture(root, tarball, expected_tree_sha256=self.sha(b"unused"))

    def test_existing_matching_runtime_is_idempotent_and_repairs_locator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tarball = self.make_tarball(root)
            _, target, locator = self.provision_fixture(root, tarball)
            data = tarball.read_bytes()
            tree_digest = self.tar_tree_digest(tarball)
            locator.unlink()
            before = os.stat(target).st_ino
            opener = mock.Mock(side_effect=AssertionError("must not download"))
            result, _, _ = self.provision_fixture(
                root, tarball=None, opener=opener,
                expected_size=len(data), expected_sha256=self.sha(data),
                expected_tree_sha256=tree_digest,
            )
            self.assertEqual(result, target)
            self.assertEqual(os.stat(target).st_ino, before)
            self.assertTrue(locator.exists())
            opener.assert_not_called()

    def test_forged_self_consistent_existing_runtime_is_refused_by_external_tree_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "support/runtimes/v1.7.0"
            locator = root / "support/codex-plugin/runtime.json"
            files = self.package_files()
            for name, data in files.items():
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            (target / "plugin/hermes/jackal_hermes").chmod(0o755)
            package_digest = self.sha(b"public outer package pin")
            metadata = provisioner._package_metadata(
                epoch="v1.7.0", asset=provisioner.ASSET,
                size=24, digest=package_digest,
            )
            (target / ".jackal-package.json").write_text(json.dumps(metadata) + "\n")
            with self.assertRaises(provisioner.ProvisionError):
                provisioner.provision(
                    runtime_target=target, locator_path=locator,
                    expected_size=24, expected_sha256=package_digest,
                    expected_tree_sha256=self.sha(b"trusted release SHA256SUMS bytes"),
                    system="Darwin", machine="arm64",
                )
            self.assertFalse(locator.exists())

    def test_atomic_install_race_never_overwrites_loser_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tarball = self.make_tarball(root)

            def lose_race(source, target):
                target.mkdir()
                (target / "racer-owned").write_text("preserve")
                raise FileExistsError("race loser")

            with self.assertRaises(provisioner.ProvisionError):
                self.provision_fixture(root, tarball, install_no_replace=lose_race)
            target = root / "support/runtimes/v1.7.0"
            self.assertEqual((target / "racer-owned").read_text(), "preserve")
            self.assertFalse((target / "plugin/hermes/jackal_hermes").exists())

    def test_existing_divergent_or_invalid_runtime_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tarball = self.make_tarball(root)
            target = root / "support/runtimes/v1.7.0"
            target.mkdir(parents=True)
            sentinel = target / "operator-data"
            sentinel.write_text("keep")
            with self.assertRaises(provisioner.ProvisionError):
                self.provision_fixture(root, tarball)
            self.assertEqual(sentinel.read_text(), "keep")

    def test_check_is_read_only_and_never_repairs_missing_locator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tarball = self.make_tarball(root)
            _, target, locator = self.provision_fixture(root, tarball)
            locator.unlink()
            opener = mock.Mock(side_effect=AssertionError("must not download"))
            checked = provisioner.provision(
                check_only=True, runtime_target=target, locator_path=locator,
                expected_size=tarball.stat().st_size,
                expected_sha256=self.sha(tarball.read_bytes()), opener=opener,
                expected_tree_sha256=self.tar_tree_digest(tarball),
                system="Darwin", machine="arm64",
            )
            self.assertEqual(checked, target)
            self.assertFalse(locator.exists())
            opener.assert_not_called()

    def test_pinned_constants_and_default_paths(self):
        self.assertEqual(provisioner.EPOCH, "v1.7.3")
        self.assertEqual(provisioner.ASSET, "jackal-v1.7.3-macos-arm64.tar.gz")
        self.assertEqual(
            provisioner.URL,
            "https://github.com/AnubisQuantumCipher/jackal/releases/download/v1.7.3/jackal-v1.7.3-macos-arm64.tar.gz",
        )
        self.assertEqual(provisioner.PACKAGE_SIZE, 158362703)
        self.assertEqual(provisioner.EXTRACTED_SIZE, 555507432)
        self.assertEqual(
            provisioner.PACKAGE_SHA256,
            "c030076186791a551d7818412e39ea895da0f16a2fad88877554ff390c284d9c",
        )
        self.assertEqual(
            provisioner.SHA256SUMS_SHA256,
            "15b179469a3519d124706a1b3281710ca2870e28a7073d107ac15eec156f2894",
        )
        self.assertEqual(
            provisioner.default_runtime_target(Path("/Users/tester")),
            Path("/Users/tester/Library/Application Support/JACKAL/runtimes/v1.7.3"),
        )

    def test_cli_rejects_relative_tarball_with_one_bounded_line_and_no_traceback(self):
        stderr = io.StringIO()
        with mock.patch("sys.stderr", stderr):
            result = provisioner.main(["--tarball", "relative.tar.gz"])
        lines = stderr.getvalue().splitlines()
        self.assertEqual(result, 1)
        self.assertEqual(len(lines), 1)
        self.assertLessEqual(len(lines[0]), 320)
        self.assertNotIn("Traceback", lines[0])

    def test_cli_parse_failure_is_one_bounded_line_without_system_exit(self):
        stderr = io.StringIO()
        with mock.patch("sys.stderr", stderr):
            result = provisioner.main(["--unknown"])
        lines = stderr.getvalue().splitlines()
        self.assertEqual(result, 1)
        self.assertEqual(len(lines), 1)
        self.assertLessEqual(len(lines[0]), 320)
        self.assertNotIn("Traceback", lines[0])


if __name__ == "__main__":
    unittest.main()
