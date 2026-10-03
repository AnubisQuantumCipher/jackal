#!/usr/bin/env python3
"""Focused resource and request-boundary tests; no guest or private input."""
import errno
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'transport/linux_aarch64'))
import sealed_runtime_runner as runner

PUBLIC = b'{"jsonrpc":"2.0","id":"fixture","method":"jackal_verify_receipt","params":{}}'


class TransportTests(unittest.TestCase):
    def test_unexpected_tail_is_rejected_after_one_byte(self):
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b'public-unexpected-tail')
            with os.fdopen(read_fd, 'rb', buffering=0) as stream:
                with self.assertRaisesRegex(runner.BrokerRefusal, 'guest-unexpected-tail'):
                    runner._expect_eof(stream, time.monotonic() + 1)
                self.assertEqual(os.read(stream.fileno(), 4096), b'ublic-unexpected-tail')
        finally:
            os.close(write_fd)

    def test_invalid_requests_refuse_before_reading_boot_files(self):
        for payload in (b'{}', PUBLIC.replace(b'"params":{}', b'"params":{},"params":{}'),
                        PUBLIC.replace(b'"fixture"', b'NaN'),
                        PUBLIC.replace(b'jackal_verify_receipt', b'jackal_exact'),
                        PUBLIC.replace(b'"jackal_verify_receipt"', b'[]')):
            with self.subTest(payload=payload), self.assertRaises(runner.BrokerRefusal):
                runner.replay(Path('/not-a-fixture'), payload)

    def fixture(self, root):
        manifest = {'schema': 'jackal-sealed-runtime-guest-development-v1',
                    'release_authorized': False}
        for name, key in (('Image', 'kernel_sha256'), ('guest.cpio.gz', 'initramfs_sha256'),
                          ('runtime.ext4', 'runtime_image_sha256')):
            data = ('public-' + name).encode()
            (root / name).write_bytes(data)
            manifest[key] = hashlib.sha256(data).hexdigest()
        (root / 'development-manifest.json').write_text(json.dumps(manifest))

    def check_cleanup(self, fail_at):
        descriptors = []
        real_snapshot = runner._snapshot
        def tracked(data):
            if len(descriptors) == fail_at:
                raise OSError('public-fixture snapshot failure')
            fd = real_snapshot(data)
            descriptors.append(fd)
            return fd
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            with patch.object(runner, '_snapshot', tracked), patch.object(
                    runner.subprocess, 'Popen', side_effect=OSError('public launch failure')):
                with self.assertRaises(OSError):
                    runner.replay(root, PUBLIC)
        self.assertTrue(descriptors)
        for fd in descriptors:
            with self.assertRaises(OSError) as caught:
                os.fstat(fd)
            self.assertEqual(caught.exception.errno, errno.EBADF)

    def test_partial_snapshot_failure_closes_prior_descriptors(self):
        self.check_cleanup(1)

    def test_launch_failure_closes_all_snapshots(self):
        self.check_cleanup(99)


if __name__ == '__main__':
    unittest.main()
