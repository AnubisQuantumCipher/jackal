#!/usr/bin/env python3
"""Privacy contract for the one sanitized live-session transcript event."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPT = ROOT / "evals/v2/receipts/codex_w3_autonomous_2026-08-20.jsonl"
SUMMARY = ROOT / "evals/v2/receipts/live_tool_sessions_2026-08-20.json"


class LiveReceiptRedactionTest(unittest.TestCase):
    def test_private_context_event_is_minimally_redacted(self) -> None:
        records = [
            json.loads(line)
            for line in TRANSCRIPT.read_text(encoding="utf-8").splitlines()
        ]
        for record in records[5:7]:
            item = record["item"]
            self.assertEqual(item["type"], "command_execution")
            self.assertEqual(item["command"], "[REDACTED_PRIVATE_LOCAL_CONTEXT]")
            self.assertEqual(
                item["aggregated_output"], "[REDACTED_PRIVATE_LOCAL_CONTEXT]"
            )
            serialized = json.dumps(record, sort_keys=True)
            self.assertNotIn("/Users/", serialized)
            self.assertNotIn("sicarii", serialized)
            self.assertNotIn(".codex/memories", serialized)

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
