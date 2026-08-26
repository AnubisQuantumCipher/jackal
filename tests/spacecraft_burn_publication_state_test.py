from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PLAN = ROOT / "docs/superpowers/plans/2026-08-24-spacecraft-burn-formal-certification-v2.md"
READBACK = ROOT / "release/evidence/spacecraft_burn_release_readback_v174.json"

MERGE_COMMIT = "9a0aaca36956d1f85540888c02c879d4480fd840"
BRANCH_HEAD = "db1360be09be3cdfb259c251f8d914dc36450641"
TAG_OBJECT = "b5cdf93e993aad0f9b735c644c91fe38eacad094"
PLUGIN_VERSION = "0.1.0+codex.20260824183637"
QUALIFIED_VERDICT = (
    "CERTIFIED SAFE under the stated finite-burn ODE model, supplied input bounds, "
    "and machine-checked interval-certificate assumptions"
)
EXPECTED_ASSETS = {
    "SHA256SUMS": "b69bf795844a4586dd59fbe6ef43372e9ed12c73af8a8c17603387cd43043acc",
    "VERIFICATION.md": "cfd4559ae2106f4eca76041f5e3e5a6aee2bdfbed2f5199247a49828279be998",
    "baseline_receipt_v2.json": "77ce2f1fd9864d75992b1c6c36764e74a01bede384c4158dce53ea775e372df0",
    "baseline_witness_v2.cert": "27d5b16e08dd9f1b39774adb455a43e129bb390b9c7462f87ba93cdade87204c",
    "independent_verification_v2.json": "953f811ada6880d17db5aa5c3cd5593a7eb1cd03d2c3ea19433c25fc0c9cdda2",
    "instrument_validation_v2.json": "64483c764d3a09079ec48e2a463c20f1fd0597ab7865a5ba41103bcfba4f4f09",
    "jackal-spacecraft-burn-v1.7.4-verifier-macos-arm64.tar.gz": "933c6142ede907f4c33d54946f089925a5668e1848caba918d7c6a9632de2a8f",
    "mutation_aba_v2.json": "decbc4e3c5d8c18a591c4057e5d1ac31ef35d030c8160be761c1200f3221503f",
    "request_v2.json": "03bcad618ad60114007c74a384eb8c9432e3755b817e74bd5bdc9bd1ba6df3e7",
    "spacecraft_burn_independent_review_v1.md": "54279fb21ff4e7c327b1a2a920e6f5eb7a9853c1941d725daac81004316ef44e",
    "spacecraft_burn_proof_identity_v1.json": "ce8d7bc20f084a6ee52abc6375d667c072da42a1cd5f96ede8cce3e373e258c7",
}
EXPECTED_ASSET_SIZES = {
    "SHA256SUMS": 964,
    "VERIFICATION.md": 1471,
    "baseline_receipt_v2.json": 13812,
    "baseline_witness_v2.cert": 35939138,
    "independent_verification_v2.json": 1593,
    "instrument_validation_v2.json": 4983,
    "jackal-spacecraft-burn-v1.7.4-verifier-macos-arm64.tar.gz": 39355487,
    "mutation_aba_v2.json": 10343,
    "request_v2.json": 533,
    "spacecraft_burn_independent_review_v1.md": 14067,
    "spacecraft_burn_proof_identity_v1.json": 20261,
}


class SpacecraftBurnPublicationStateTests(unittest.TestCase):
    def test_readme_reports_the_published_qualified_release(self):
        text = README.read_text(encoding="utf-8")
        self.assertNotIn("v1.7.4 release candidate", text)
        self.assertNotIn("not yet a published release verdict", text)
        self.assertIn(QUALIFIED_VERDICT, " ".join(text.split()))
        self.assertIn(
            "https://github.com/AnubisQuantumCipher/jackal/releases/tag/v1.7.4",
            text,
        )

    def test_final_plan_records_all_eight_publication_steps_complete(self):
        text = PLAN.read_text(encoding="utf-8")
        task = text.split("### Task 14:", 1)[1].split("### Task 15:", 1)[0]
        self.assertNotRegex(task, r"^- \[ \]", re.MULTILINE)
        self.assertEqual(len(re.findall(r"^- \[x\] \*\*Step [1-8]:", task, re.MULTILINE)), 8)

    def test_readback_binds_remote_release_assets_plugin_and_protected_checkout(self):
        self.assertTrue(READBACK.is_file(), "published release readback receipt is missing")
        receipt = json.loads(READBACK.read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema"], "jackal-spacecraft-burn-release-readback-v1")
        self.assertEqual(
            receipt["terminal_state"],
            "PUBLISHED_READBACK_VERIFIED_WITH_CORRECTIVE_RELEASE_REQUIRED",
        )
        self.assertEqual(receipt["pull_request"]["head"], BRANCH_HEAD)
        self.assertEqual(receipt["pull_request"]["merge_commit"], MERGE_COMMIT)
        self.assertEqual(receipt["pull_request"]["state"], "merged")
        self.assertEqual(receipt["release"]["tag"], "v1.7.4")
        self.assertEqual(receipt["release"]["tag_object"], TAG_OBJECT)
        self.assertEqual(receipt["release"]["tag_commit"], MERGE_COMMIT)
        self.assertTrue(receipt["release"]["latest"])
        self.assertFalse(receipt["release"]["draft"])
        self.assertFalse(receipt["release"]["prerelease"])
        self.assertEqual(receipt["release"]["fresh_download_byte_matches"], 11)
        self.assertEqual(receipt["release"]["fresh_download_checksum_rows_passed"], 10)
        assets = {item["name"]: item["sha256"] for item in receipt["release"]["assets"]}
        self.assertEqual(assets, EXPECTED_ASSETS)
        asset_sizes = {item["name"]: item["bytes"] for item in receipt["release"]["assets"]}
        self.assertEqual(asset_sizes, EXPECTED_ASSET_SIZES)
        self.assertEqual(receipt["proof"]["qualified_verdict"], QUALIFIED_VERDICT)
        self.assertEqual(receipt["proof"]["logical_admissions"], 0)
        post_publication_runs = {
            item["run_id"]: item["conclusion"]
            for item in receipt["hosted_checks"]["post_merge_and_tag"]
        }
        self.assertEqual(
            post_publication_runs,
            {
                32790862073: "success",
                32790862122: "success",
                32790862155: "success",
                32790881743: "success",
                32790881818: "cancelled",
                32790881824: "success",
            },
        )
        self.assertTrue(receipt["corrective_release"]["required"])
        self.assertEqual(receipt["corrective_release"]["target"], "v1.7.5")
        self.assertEqual(receipt["plugin"]["version"], PLUGIN_VERSION)
        self.assertEqual(receipt["plugin"]["tool_count"], 41)
        self.assertEqual(receipt["plugin"]["unique_tool_count"], 41)
        self.assertEqual(
            receipt["protected_checkout"]["head"],
            "57739317b24250ff62fd9b23f67c760d9066ab94",
        )
        self.assertEqual(
            receipt["protected_checkout"]["untracked_roots"],
            ["jackal_calc.anb.zip", "jackal_calc.md", "spacecraft_burn_cert/", "website/"],
        )


if __name__ == "__main__":
    unittest.main()
