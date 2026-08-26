from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PLAN = ROOT / "docs/superpowers/plans/2026-08-24-spacecraft-burn-formal-certification-v2.md"
READBACK = ROOT / "release/evidence/spacecraft_burn_release_readback_v174.json"
READBACK_V175 = (
    ROOT / "release/evidence/spacecraft_burn_release_readback_v175.json"
)
SPACECRAFT_README = ROOT / "spacecraft_burn_cert/README.md"
REPORT = ROOT / "spacecraft_burn_cert/REPORT.md"

MERGE_COMMIT = "9a0aaca36956d1f85540888c02c879d4480fd840"
BRANCH_HEAD = "db1360be09be3cdfb259c251f8d914dc36450641"
TAG_OBJECT = "b5cdf93e993aad0f9b735c644c91fe38eacad094"
PLUGIN_VERSION = "0.1.0+codex.20260824183637"
V175_PR_HEAD = "eb69713918798f5828950d92f1003c66d2eb26ca"
V175_MERGE_COMMIT = "9a49f70b65b20907df40be99ee83e61e18adc7c5"
V175_TAG_OBJECT = "1369dacf60101c2d196d577b0319b6d5c0a72aa8"
V175_RELEASE_ID = 377032844
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

EXPECTED_V175_ASSETS = {
    "SHA256SUMS": (
        1075,
        "c177a260d5cecf5cf9341cab658f234b619cb2b81caed0f081ca592aecc65ba1",
    ),
    "VERIFICATION.md": (
        3429,
        "8e2ce70e223387ec297777e8e810d058a32cad4c6f94b44f9f595239b6b69c7a",
    ),
    "baseline_receipt_v2.json": (
        14299,
        "489eaffcdb5445262a07443c7d02421d2363f9a7e52fbc081e21a1ed29d5a8ed",
    ),
    "baseline_witness_v2.cert": (
        35939138,
        "27d5b16e08dd9f1b39774adb455a43e129bb390b9c7462f87ba93cdade87204c",
    ),
    "independent_verification_v2.json": (
        1960,
        "de716e84319e63ee2971e06586414df692e7f1d69da802917e7aa28895876246",
    ),
    "instrument_validation_v2.json": (
        5937,
        "8cb4496d33b63123b4c5cc4ee8d8956a3ff767456f45aaf1299422fdd474628a",
    ),
    "jackal-spacecraft-burn-v1.7.5-verifier-macos-arm64.tar.gz": (
        39423959,
        "7eae30a674c0d82f52644125d17025ae8aad82a7eeaa5801afbee49c220f1abf",
    ),
    "mutation_aba_v2.json": (
        13626,
        "542d0bb66359bb4960255c16bb9d8bf160f1d681e5960e630456d3995535ab35",
    ),
    "request_v2.json": (
        533,
        "03bcad618ad60114007c74a384eb8c9432e3755b817e74bd5bdc9bd1ba6df3e7",
    ),
    "spacecraft_burn_independent_review_v175.md": (
        15026,
        "f7700a20d4ff86f010667e019de0dc62b39976e6290f76209bdedcc385144a51",
    ),
    "spacecraft_burn_proof_identity_v1.json": (
        31944,
        "dc786a6e73a01278b09b899abd54555a5d268a305d745f66c4bf5480527bf876",
    ),
    "spacecraft_burn_review_clearance_v175.json": (
        358,
        "c65e33f86e60200643972e8b4f70a81ced214affe23c9049e029e91ee928c51b",
    ),
}

V175_PROOF_IDENTITIES = {
    "checker_sha256": "2e08149b735ff70a1f1b6606aeca46c9e4dbf2a7d12db2cdc0e80d37f325fa59",
    "proof_identity_file_sha256": (
        "dc786a6e73a01278b09b899abd54555a5d268a305d745f66c4bf5480527bf876"
    ),
    "proof_identity_digest_sha256": (
        "418854abbb009a25b020be6cb3799dfd3ae75d6619ad4f26032cc64fead924be"
    ),
    "request_digest": "03bcad618ad60114007c74a384eb8c9432e3755b817e74bd5bdc9bd1ba6df3e7",
    "witness_sha256": "27d5b16e08dd9f1b39774adb455a43e129bb390b9c7462f87ba93cdade87204c",
    "producer_source_sha256": (
        "d6e98c03e74847b8aea05600c3bae3681e59579506f2a0661504f6ea96e1c38a"
    ),
}

CANONICAL_CHECKER_ACCEPT = (
    "ACCEPT theorem=spacecraft_burn_certified_safe status=formal-bounded "
    "margin_lo=51450379597827184853505075 "
    "margin_hi=97148190212754394888777802 "
    "model=jackal-spacecraft-finite-burn-ode-v2 epoch=v1.7.5"
)
EXPECTED_PR_CONTEXTS = {
    ("Spacecraft burn formal certificate gate", "full-certificate-campaign"),
    (
        "Formal proof identity gate",
        "Gaussian/range source closures and axiom audits",
    ),
    (
        "Formal proof identity gate",
        "claim-kernel admission and surface locks (engine-free)",
    ),
    ("JACKAL Codex plugin", "macOS arm64 plugin gates"),
    ("CodeRabbit", "CodeRabbit"),
}
EXPECTED_POST_MERGE_RUNS = {
    32916885108: ("JACKAL Codex plugin", "master"),
    32916885112: ("Formal proof identity gate", "master"),
    32916885129: ("Spacecraft burn formal certificate gate", "master"),
    32934182499: ("JACKAL Codex plugin", "v1.7.5"),
    32934182467: ("Formal proof identity gate", "v1.7.5"),
    32934182495: ("Spacecraft burn formal certificate gate", "v1.7.5"),
}


def assert_v175_security_contract(
    testcase: unittest.TestCase,
    receipt: dict,
) -> None:
    release = receipt["release"]
    assets = release["assets"]
    names = [asset["name"] for asset in assets]
    testcase.assertEqual(len(assets), 12)
    testcase.assertEqual(len(set(names)), 12)
    testcase.assertEqual(
        {
            asset["name"]: (asset["bytes"], asset["sha256"])
            for asset in assets
        },
        EXPECTED_V175_ASSETS,
    )
    testcase.assertTrue(release["title_and_notes_byte_match"])
    testcase.assertEqual(
        release["notes_sha256"],
        "ae27adbb2447455326230682cf7c072e279036004bb67559a9532744a2522160",
    )
    testcase.assertEqual(
        receipt["public_replay"],
        {
            "checksum_manifest_sha256": (
                "c177a260d5cecf5cf9341cab658f234b619cb2b81caed0f081ca592aecc65ba1"
            ),
            "checksum_rows_passed": 11,
            "asset_byte_matches": 12,
            "archive_safe_extraction_completed": True,
            "checker_result_line": CANONICAL_CHECKER_ACCEPT,
            "outer_verifier_status": "ACCEPT",
            "outer_verifier_reasons": [],
            "outer_verifier_output_sha256": (
                "de716e84319e63ee2971e06586414df692e7f1d69da802917e7aa28895876246"
            ),
            "structured_claim_gate": "PASS",
        },
    )

    hosted = receipt["pull_request"]["hosted_contexts"]
    testcase.assertEqual(
        (hosted["observed"], hosted["passed"], hosted["failed"]),
        (5, 5, 0),
    )
    contexts = hosted["contexts"]
    testcase.assertEqual(len(contexts), 5)
    testcase.assertEqual(
        {(context["workflow"], context["name"]) for context in contexts},
        EXPECTED_PR_CONTEXTS,
    )
    testcase.assertEqual({context["state"] for context in contexts}, {"success"})

    runs = receipt["hosted_checks"]["post_merge_and_tag"]
    testcase.assertEqual(len(runs), 6)
    testcase.assertEqual(
        {
            run["run_id"]: (run["workflow"], run["ref"])
            for run in runs
        },
        EXPECTED_POST_MERGE_RUNS,
    )
    testcase.assertEqual({run["event"] for run in runs}, {"push"})
    testcase.assertEqual({run["head_sha"] for run in runs}, {V175_MERGE_COMMIT})
    testcase.assertEqual({run["conclusion"] for run in runs}, {"success"})

    plugin = receipt["plugin"]
    testcase.assertEqual(
        plugin["ordered_tool_names_sha256"],
        "851a50fb7b82d23e2e4dc59d3617659e7f161ed4f2f9fb0bc572f6c939c459bd",
    )
    testcase.assertEqual(
        plugin["full_definitions_sha256"],
        "03279ea328d028371b336fe2eb9decf3caf500a21a8d988058e51696c3975df0",
    )
    testcase.assertEqual(
        plugin["pinned_package_sha256"],
        "68b0e7850fcb60358633908f70ffcf405cbbef103b04d3d93dd1298789e505ae",
    )
    testcase.assertTrue(plugin["source_cache_byte_match"])
    testcase.assertEqual(plugin["plugin_tests_passed"], 220)
    testcase.assertEqual(plugin["capability_tests_passed"], 35)


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

    def test_v175_public_release_readback_binds_exact_remote_state(self):
        self.assertTrue(
            READBACK_V175.is_file(),
            "published v1.7.5 release readback receipt is missing",
        )
        receipt = json.loads(READBACK_V175.read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["schema"],
            "jackal-spacecraft-burn-release-readback-v1",
        )
        self.assertEqual(receipt["terminal_state"], "PUBLISHED_READBACK_VERIFIED")
        self.assertEqual(receipt["pull_request"]["number"], 17)
        self.assertEqual(receipt["pull_request"]["head"], V175_PR_HEAD)
        self.assertEqual(
            receipt["pull_request"]["merge_commit"],
            V175_MERGE_COMMIT,
        )
        self.assertEqual(receipt["pull_request"]["state"], "merged")
        release = receipt["release"]
        self.assertEqual(release["id"], V175_RELEASE_ID)
        self.assertEqual(
            release["name"],
            "JACKAL v1.7.5 - Spacecraft finite-burn certification",
        )
        self.assertEqual(
            release["url"],
            "https://github.com/AnubisQuantumCipher/jackal/releases/tag/v1.7.5",
        )
        self.assertEqual(release["tag"], "v1.7.5")
        self.assertEqual(release["tag_object"], V175_TAG_OBJECT)
        self.assertEqual(release["tag_commit"], V175_MERGE_COMMIT)
        self.assertTrue(release["latest"])
        self.assertFalse(release["draft"])
        self.assertFalse(release["prerelease"])
        self.assertEqual(release["fresh_download_byte_matches"], 12)
        self.assertEqual(release["fresh_download_checksum_rows_passed"], 11)
        assets = {
            asset["name"]: (asset["bytes"], asset["sha256"])
            for asset in release["assets"]
        }
        self.assertEqual(assets, EXPECTED_V175_ASSETS)

    def test_v175_readback_binds_public_replay_and_unique_remote_rows(self):
        receipt = json.loads(READBACK_V175.read_text(encoding="utf-8"))
        assert_v175_security_contract(self, receipt)

    def test_v175_security_contract_rejects_laundered_readback_copies(self):
        receipt = json.loads(READBACK_V175.read_text(encoding="utf-8"))
        mutations = []

        duplicate_asset = copy.deepcopy(receipt)
        duplicate_asset["release"]["assets"].append(
            copy.deepcopy(duplicate_asset["release"]["assets"][0])
        )
        mutations.append(("duplicate-asset", duplicate_asset))

        missing_formal_context = copy.deepcopy(receipt)
        missing_formal_context["pull_request"]["hosted_contexts"]["contexts"] = [
            context
            for context in missing_formal_context["pull_request"][
                "hosted_contexts"
            ]["contexts"]
            if context["name"]
            != "claim-kernel admission and surface locks (engine-free)"
        ]
        mutations.append(("missing-formal-context", missing_formal_context))

        for label, path, replacement in (
            (
                "unsafe-extraction",
                ("public_replay", "archive_safe_extraction_completed"),
                False,
            ),
            (
                "notes-byte-drift",
                ("release", "title_and_notes_byte_match"),
                False,
            ),
            (
                "plugin-cache-drift",
                ("plugin", "source_cache_byte_match"),
                False,
            ),
            (
                "checker-refusal",
                ("public_replay", "checker_result_line"),
                "REJECT forged",
            ),
            (
                "outer-refusal",
                ("public_replay", "outer_verifier_status"),
                "REFUSED",
            ),
            (
                "outer-reasons",
                ("public_replay", "outer_verifier_reasons"),
                ["witness-hash-mismatch"],
            ),
            (
                "outer-output-drift",
                ("public_replay", "outer_verifier_output_sha256"),
                "0" * 64,
            ),
        ):
            changed = copy.deepcopy(receipt)
            target = changed
            for component in path[:-1]:
                target = target[component]
            target[path[-1]] = replacement
            mutations.append((label, changed))

        for label, changed in mutations:
            with self.subTest(label=label), self.assertRaises(AssertionError):
                assert_v175_security_contract(self, changed)

    def test_v175_readback_binds_successful_pr_master_and_tag_workflows(self):
        receipt = json.loads(READBACK_V175.read_text(encoding="utf-8"))
        expected_pr_workflows = {
            "CodeRabbit",
            "Formal proof identity gate",
            "JACKAL Codex plugin",
            "Spacecraft burn formal certificate gate",
        }
        contexts = receipt["pull_request"]["hosted_contexts"]["contexts"]
        self.assertTrue(contexts)
        self.assertEqual(
            {context["workflow"] for context in contexts},
            expected_pr_workflows,
        )
        self.assertEqual({context["event"] for context in contexts}, {"pull_request"})
        self.assertEqual({context["state"] for context in contexts}, {"success"})

        expected_push_workflows = {
            "Formal proof identity gate",
            "JACKAL Codex plugin",
            "Spacecraft burn formal certificate gate",
        }
        runs = receipt["hosted_checks"]["post_merge_and_tag"]
        for ref in ("master", "v1.7.5"):
            selected = [run for run in runs if run["ref"] == ref]
            self.assertEqual(
                {run["workflow"] for run in selected},
                expected_push_workflows,
            )
            self.assertEqual({run["event"] for run in selected}, {"push"})
            self.assertEqual(
                {run["head_sha"] for run in selected},
                {V175_MERGE_COMMIT},
            )
            self.assertEqual({run["conclusion"] for run in selected}, {"success"})
        self.assertTrue(receipt["hosted_checks"]["all_master_push_runs_successful"])
        self.assertTrue(receipt["hosted_checks"]["all_tag_push_runs_successful"])

    def test_v175_readback_binds_proof_review_plugin_and_checkout_identities(self):
        receipt = json.loads(READBACK_V175.read_text(encoding="utf-8"))
        proof = receipt["proof"]
        self.assertEqual(proof["qualified_verdict"], QUALIFIED_VERDICT)
        self.assertEqual(proof["assurance_class"], "formal-bounded")
        self.assertEqual(proof["model_id"], "jackal-spacecraft-finite-burn-ode-v2")
        self.assertEqual(proof["release_epoch"], "v1.7.5")
        self.assertEqual(
            proof["soundness_theorem"],
            "JackalIv.Spacecraft.spacecraft_burn_certified_safe",
        )
        self.assertEqual(
            proof["observed_theorem_axioms"],
            ["propext", "Classical.choice", "Quot.sound"],
        )
        self.assertEqual(proof["tracked_lean_files"], 57)
        self.assertEqual(proof["named_theorems"], 29)
        self.assertEqual(proof["logical_admissions"], 0)
        for field, expected in V175_PROOF_IDENTITIES.items():
            self.assertEqual(proof[field], expected)
        review = proof["independent_review"]
        self.assertEqual(review["completed_passes"], 37)
        self.assertEqual(review["resolved_findings"], 17)
        self.assertEqual(review["invalid_findings"], 1)
        self.assertEqual(review["unresolved_release_blocking"], 0)
        self.assertEqual(
            review["asset_sha256"],
            "f7700a20d4ff86f010667e019de0dc62b39976e6290f76209bdedcc385144a51",
        )
        self.assertEqual(
            review["clearance_sha256"],
            "c65e33f86e60200643972e8b4f70a81ced214affe23c9049e029e91ee928c51b",
        )

        plugin = receipt["plugin"]
        self.assertEqual(plugin["impact"], "none")
        self.assertEqual(plugin["version"], PLUGIN_VERSION)
        self.assertEqual(plugin["tool_count"], 41)
        self.assertEqual(plugin["unique_tool_count"], 41)
        self.assertEqual(
            plugin["aggregate_identity_sha256"],
            "b2d62d374a54ffdaf090df3a6ea24ef9f6a64f9dde8c5189c29d67bd3b12ece8",
        )
        checkout = receipt["protected_checkout"]
        self.assertEqual(checkout["path"], "$HOME/Desktop/Projects/jackal-calc")
        self.assertEqual(
            checkout["branch"],
            "feat/mathematical-evidence-kernel-v1.6.0",
        )
        self.assertEqual(
            checkout["head"],
            "57739317b24250ff62fd9b23f67c760d9066ab94",
        )
        self.assertEqual(checkout["tracked_changes"], [])
        self.assertEqual(
            checkout["untracked_roots"],
            [
                "jackal_calc.anb.zip",
                "jackal_calc.md",
                "spacecraft_burn_cert/",
                "website/",
            ],
        )
        self.assertFalse(checkout["mutation_performed_by_publication_work"])

    def test_v175_readback_keeps_all_release_nonclaims_explicit(self):
        receipt = json.loads(READBACK_V175.read_text(encoding="utf-8"))
        text = " ".join(receipt["nonclaims"]).lower()
        for required in (
            "physical",
            "supplied input",
            "lean compiler",
            "not formally verified",
            "not external academic peer review",
            "unsigned",
            "no new jackel tool",
            "v1.7.4",
        ):
            self.assertIn(required, text)

    def test_v175_docs_link_published_release_and_readback_not_candidate_state(self):
        release_url = (
            "https://github.com/AnubisQuantumCipher/jackal/releases/tag/v1.7.5"
        )
        for path in (README, SPACECRAFT_README, REPORT):
            with self.subTest(path=str(path)):
                text = path.read_text(encoding="utf-8")
                normalized = " ".join(text.split())
                self.assertIn(release_url, text)
                self.assertIn(
                    "spacecraft_burn_release_readback_v175.json",
                    text,
                )
                self.assertIn(QUALIFIED_VERDICT, normalized)
                self.assertNotIn("v1.7.5 candidate", normalized.lower())
                self.assertNotIn("exists only after publication", normalized.lower())
                self.assertNotIn("only after the fresh public-download", normalized.lower())

    def test_task15_steps_four_through_eight_have_concrete_completion_evidence(self):
        text = PLAN.read_text(encoding="utf-8")
        task = text.split("### Task 15:", 1)[1]
        for step in range(4, 9):
            marker = f"**Step {step}:"
            self.assertRegex(
                task,
                rf"(?m)^- \[x\] {re.escape(marker)}",
            )
            section = task.split(marker, 1)[1]
            if step < 8:
                section = section.split(f"**Step {step + 1}:", 1)[0]
            self.assertIn("Completion evidence:", section)


if __name__ == "__main__":
    unittest.main()
