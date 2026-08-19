#!/usr/bin/env python3
"""Guard: the v1.6.0 claim replay must stay pinned to archived registry bytes.

The hosted-CI gate `release/tools/ci_claim_admission.py` replays a recorded
v1.6.0 claim bundle. That bundle records the inference-registry digest inside
its own body, so the replay is only honest if it is fed the exact registry
bytes that digest names -- from the immutable archive, never from the mutable
live file.

The live `release/claim/inference_registry_v1.json` has since moved to
registry_version 2. The tempting "fix" when the gate goes red is to repoint the
replay at the live file and repin the fixture. That would make recorded
evidence assert a verification against bytes it was never verified against --
laundering, and precisely the defect the claim program exists to catch. The
legitimate direction is the reverse: the archived bytes must be made equal to
what the fixture already pins.

These tests make that judgement mechanical rather than a comment someone can
delete: they read the constant the gate actually uses, inspect the argv it
actually builds, and prove by mutation that repointing it really does break the
gate rather than passing silently.

Read-only with respect to `release/evidence/**`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "release" / "tools" / "ci_claim_admission.py"
FIXTURE = ROOT / "release" / "evidence" / "ci_claim_fixture_v160"
LIVE_REGISTRY = ROOT / "release" / "claim" / "inference_registry_v1.json"
ARCHIVE_DIR = ROOT / "release" / "claim" / "archive"


def load_gate():
    spec = importlib.util.spec_from_file_location("ci_claim_admission", GATE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the v1.6.0 claim admission gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HistoricalReplayPinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = load_gate()
        cls.pins = json.loads((FIXTURE / "pins.json").read_text(encoding="utf-8"))

    def test_replay_registry_is_archived_not_live(self) -> None:
        pinned = Path(self.gate.HISTORICAL_V160_INFERENCE_REGISTRY).resolve()
        self.assertNotEqual(
            pinned,
            LIVE_REGISTRY.resolve(),
            "the v1.6.0 replay was repointed at the live inference registry; "
            "a v1.6.0 bundle must replay against v1.6.0 bytes",
        )
        self.assertEqual(
            pinned.parent,
            ARCHIVE_DIR.resolve(),
            f"the v1.6.0 replay registry must live under {ARCHIVE_DIR}",
        )
        self.assertTrue(pinned.is_file(), f"archived registry missing: {pinned}")

    def test_archived_bytes_match_the_frozen_fixture_pin(self) -> None:
        pinned = Path(self.gate.HISTORICAL_V160_INFERENCE_REGISTRY)
        self.assertEqual(
            sha256_file(pinned),
            self.pins["expected_inference_registry_sha256"],
            "archived registry bytes do not hash to the digest the frozen "
            "v1.6.0 fixture recorded",
        )

    def test_live_registry_is_not_silently_substitutable(self) -> None:
        # If the live registry ever hashes to the v1.6.0 pin again, this guard
        # would pass for the wrong reason: repointing the replay at the live
        # file would be undetectable. Fail loudly instead of guarding nothing.
        self.assertNotEqual(
            sha256_file(LIVE_REGISTRY),
            self.pins["expected_inference_registry_sha256"],
            "live registry now hashes to the v1.6.0 pin, so this guard can no "
            "longer distinguish archived from live bytes; re-derive the guard",
        )

    def test_gate_argv_feeds_the_archived_registry(self) -> None:
        captured: dict[str, list[str]] = {}

        def capture(argv, **_kwargs):
            captured["argv"] = list(argv)
            raise AssertionError("subprocess must not run in this test")

        with mock.patch.object(self.gate.subprocess, "run", capture):
            with self.assertRaises(AssertionError):
                self.gate.verify(FIXTURE / "bundle.json", self.pins)

        argv = captured["argv"]
        flag = argv.index("--expected-inference-registry")
        supplied = Path(argv[flag + 1]).resolve()
        self.assertEqual(supplied.parent, ARCHIVE_DIR.resolve())
        self.assertNotIn(
            str(LIVE_REGISTRY.resolve()),
            argv,
            "the live registry path reached the v1.6.0 replay argv",
        )

    def test_repointing_at_the_live_registry_actually_breaks_the_gate(self) -> None:
        # Mutation control. Without this, the three checks above could all pass
        # while the gate itself no longer depends on the pinned path at all.
        with mock.patch.object(
            self.gate, "HISTORICAL_V160_INFERENCE_REGISTRY", LIVE_REGISTRY
        ):
            completed = self.gate.verify(FIXTURE / "bundle.json", self.pins)
        self.assertNotEqual(
            completed.returncode,
            0,
            "repointing the v1.6.0 replay at the live registry did NOT fail; "
            "the archival pin is not load-bearing",
        )
        self.assertIn("registry-inference-mismatch", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
