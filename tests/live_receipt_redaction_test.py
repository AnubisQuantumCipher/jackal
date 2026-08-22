#!/usr/bin/env python3
"""Privacy contract for committed live-session transcript streams."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPT = ROOT / "evals/v2/receipts/codex_w3_autonomous_2026-08-20.jsonl"
TRANSCRIPTS = sorted((ROOT / "evals/v2/receipts").glob("codex_*.jsonl"))
SUMMARY = ROOT / "evals/v2/receipts/live_tool_sessions_2026-08-20.json"
FORBIDDEN_PRIVATE_TOKENS = (
    "/Users/",
    ".codex/config.toml",
    ".codex/plugins/cache",
    ".codex/memories",
)
REDACTION_MARKER = "[REDACTED_PRIVATE_LOCAL_CONTEXT]"


class LiveReceiptRedactionTest(unittest.TestCase):
    def test_all_committed_codex_transcripts_hide_private_local_paths(self) -> None:
        self.assertGreaterEqual(len(TRANSCRIPTS), 3)
        for transcript in TRANSCRIPTS:
            raw = transcript.read_text(encoding="utf-8")
            with self.subTest(transcript=transcript.name):
                for token in FORBIDDEN_PRIVATE_TOKENS:
                    self.assertNotIn(token, raw)

    def test_private_context_event_is_minimally_redacted(self) -> None:
        records = [
            json.loads(line)
            for line in TRANSCRIPT.read_text(encoding="utf-8").splitlines()
        ]
        redacted = [
            record
            for record in records
            if record.get("item", {}).get("type") == "command_execution"
            and record["item"].get("command") == REDACTION_MARKER
            and record["item"].get("aggregated_output") == REDACTION_MARKER
        ]
        self.assertEqual(len(redacted), 2)
        for record in redacted:
            item = record["item"]
            self.assertEqual(item["type"], "command_execution")
            self.assertEqual(item["command"], REDACTION_MARKER)
            self.assertEqual(item["aggregated_output"], REDACTION_MARKER)

    def test_summary_binds_exact_post_redaction_bytes(self) -> None:
        document = json.loads(SUMMARY.read_text(encoding="utf-8"))
        relative = TRANSCRIPT.relative_to(ROOT).as_posix()
        row = next(item for item in document["sessions"] if item["path"] == relative)
        raw = TRANSCRIPT.read_bytes()
        self.assertEqual(row["bytes"], len(raw))
        self.assertEqual(row["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertIn("redacted", row["content_state"])


if __name__ == "__main__":
    unittest.main()
