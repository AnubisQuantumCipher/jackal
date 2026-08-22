#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION = ROOT / "release/evidence/architect_release_authorization_v173.json"


class ReleaseAuthorizationV173Test(unittest.TestCase):
    def test_architect_approved_both_trust_surfaces_and_release_actions(self) -> None:
        document = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
        self.assertEqual(document["schema"], "jackal-release-authorization-v1")
        self.assertEqual(document["release"], "v1.7.3")
        self.assertEqual(document["authority"], "architect")
        self.assertEqual(
            document["instructions"],
            [
                "Merge and do whatever else you have to do. Don’t leave nothing undone",
                "Use your best jusment on all desisions",
            ],
        )
        self.assertEqual(
            document["decisions"],
            {
                "domain_pack_compatibility_minimum_approved": True,
                "inventory_safe_v1_accept_conditions_approved": True,
                "jackal_merge_tag_release_approved": True,
                "hermes_merge_tag_release_install_approved": True,
                "upstream_pr_update_approved": True,
            },
        )
        self.assertIn("not-a-cryptographic-signature", document["non_claims"])
        self.assertIn(
            "does-not-override-third-party-permissions-or-branch-protection",
            document["non_claims"],
        )


if __name__ == "__main__":
    unittest.main()
