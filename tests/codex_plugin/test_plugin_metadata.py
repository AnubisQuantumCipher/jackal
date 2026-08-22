import json
import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPOSITORY_ROOT / "plugins" / "jackel"
MANIFEST_PATH = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
MARKETPLACE_PATH = REPOSITORY_ROOT / ".agents" / "plugins" / "marketplace.json"
MCP_PATH = PLUGIN_ROOT / ".mcp.json"
SKILL_PATH = PLUGIN_ROOT / "skills" / "jackel" / "SKILL.md"
IDENTITY_PATH = PLUGIN_ROOT / "PLUGIN_IDENTITY.sha256"
README_PATH = PLUGIN_ROOT / "README.md"
LAUNCHER_PATH = PLUGIN_ROOT / "scripts" / "launch_mcp.zsh"
SERVER_PATH = PLUGIN_ROOT / "mcp" / "server.py"
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "jackal-codex-plugin.yml"
DESIGN_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-08-17-jackel-codex-plugin-design.md"
)
PLAN_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-08-17-jackel-codex-plugin.md"
)
APPROVED_SKILL_DESCRIPTION = (
    "Route claim-aware computation, domain-pack, and Anubis program evidence "
    "through JACKAL without overstating assurance."
)


class PluginMetadataTests(unittest.TestCase):
    def load_json(self, path):
        def reject_duplicate_keys(pairs):
            parsed = {}
            for key, value in pairs:
                if key in parsed:
                    raise ValueError(f"duplicate JSON key: {key}")
                parsed[key] = value
            return parsed

        with path.open(encoding="utf-8") as handle:
            return json.load(handle, object_pairs_hook=reject_duplicate_keys)

    def assert_marketplace_entry(self, entry):
        self.assertEqual(set(entry), {"name", "source", "policy", "category"})
        self.assertNotIn("products", entry)
        self.assertEqual(set(entry["policy"]), {"installation", "authentication"})
        self.assertNotIn("products", entry["policy"])

    def assert_no_placeholders(self, paths):
        for path in paths:
            self.assertNotIn("[TO" + "DO:", path.read_text(encoding="utf-8"))

    @staticmethod
    def parse_skill_frontmatter(skill):
        lines = skill.splitlines()
        if not lines or lines[0] != "---":
            raise ValueError("frontmatter must begin with ---")

        try:
            closing_index = lines.index("---", 1)
        except ValueError as error:
            raise ValueError("frontmatter must end with ---") from error

        frontmatter = {}
        for line in lines[1:closing_index]:
            if line != line.strip() or ":" not in line:
                raise ValueError("malformed frontmatter mapping line")
            key, value = line.split(":", 1)
            if not key or not key.replace("_", "").replace("-", "").isalnum():
                raise ValueError("malformed frontmatter key")
            value = value.strip()
            if not value:
                raise ValueError("frontmatter values must be nonempty")
            if key in frontmatter:
                raise ValueError(f"duplicate frontmatter key: {key}")
            frontmatter[key] = value

        if set(frontmatter) != {"name", "description"}:
            raise ValueError("frontmatter must contain exactly name and description")

        return frontmatter

    def test_legacy_ids_remain_jackel_but_public_product_is_jackal(self):
        desired_root = REPOSITORY_ROOT / "plugins" / "jackel"
        self.assertTrue(desired_root.is_dir(), "plugins/jackel must be the plugin root")
        self.assertFalse((REPOSITORY_ROOT / "plugins" / "jackal").exists())

        manifest = self.load_json(desired_root / ".codex-plugin" / "plugin.json")
        marketplace = self.load_json(MARKETPLACE_PATH)
        mcp = self.load_json(desired_root / ".mcp.json")
        skill = (desired_root / "skills" / "jackel" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertEqual(manifest["name"], "jackel")
        self.assertEqual(manifest["interface"]["displayName"], "JACKAL")
        self.assertIn("JACKAL", manifest["description"])
        self.assertIn("JACKAL", manifest["interface"]["longDescription"])
        self.assertIn("JACKAL", manifest["interface"]["defaultPrompt"][0])
        self.assertNotIn("JACKEL", json.dumps(manifest, sort_keys=True))
        self.assertEqual(
            marketplace["plugins"],
            [
                {
                    "name": "jackel",
                    "source": {"source": "local", "path": "./plugins/jackel"},
                    "policy": {
                        "installation": "AVAILABLE",
                        "authentication": "ON_INSTALL",
                    },
                    "category": "Productivity",
                }
            ],
        )
        self.assertEqual(set(mcp["mcpServers"]), {"jackel"})
        self.assertEqual(self.parse_skill_frontmatter(skill)["name"], "jackel")
        self.assertIn("# JACKAL numerical-trust operator", skill)
        self.assertNotIn("JACKEL", skill)
        server = SERVER_PATH.read_text(encoding="utf-8")
        self.assertIn("Preserve JACKAL status", server)
        self.assertNotIn("JACKEL", server)

    def test_design_scopes_adapter_local_busy_refusal_out_of_backend_fidelity(self):
        design = DESIGN_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "Except for the adapter-local `plugin-busy` admission refusal, the "
            "adapter must not manufacture",
            design,
        )

    def test_design_records_quality_closure_and_unrun_fresh_host_gate(self):
        design = DESIGN_PATH.read_text(encoding="utf-8")
        for required in (
            "monotonic total download deadline",
            "bounded response-byte queue",
            "duplicate-key rejection and canonical JSON",
            "Only `ESRCH` or `ProcessLookupError`",
            "`EPERM` is a bounded named failure unless a bounded re-observation",
            "never reinterpret a permission error itself as proof of absence",
            "same provisioner-owned sanitized environment",
            "`--host-live`",
            "`codex mcp list --json`",
            "exact active `jackel` MCP declaration and resolved cache cwd",
            "thread-start, turn-start, claim-start, claim-complete, verify-start, verify-complete, turn-complete",
            "`item.updated`",
            "unknown top-level or active-capability event",
            "`in_progress` to `completed`",
            "between its correlated start and completion",
            "nonnegative `input_tokens`, `cached_input_tokens`, and `output_tokens`",
            "`cache_write_input_tokens` and `reasoning_output_tokens` are the only permitted optional counters",
            "does not itself constitute fresh-host evidence",
            "`macos-14`",
            "snapshot cleanup failure is a named startup refusal",
            "caller-supplied external trust anchor",
            "does not authenticate an official Codex binary",
            "passive item identifiers",
            "terminal-only passive completion",
            "passwd account home",
            "ancestor or descendant",
            "before every Codex install command",
            "retains the unreaped leader anchor",
            "host text content and structured content",
            "observer failure cannot suppress",
            "canonical event and item keys",
            "passive item text",
            "exact successful claim and verifier result key sets",
            "`claim-verify=verified`",
            "`bundle.digest=`",
            "retained leader plus only zombie members",
        ):
            with self.subTest(required=required):
                self.assertIn(required, design)

        plan = PLAN_PATH.read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"(?m)^/opt/homebrew/bin/python3\b", plan),
            "historical plan must not directly invoke one machine-specific Python",
        )
        self.assertIn("--host-live", plan)
        self.assertIn("fresh-task host acceptance remains unproven", plan)
        self.assertIn("caller-supplied external trust anchor", plan)
        self.assertIn("does not authenticate an official Codex binary", plan)

    def test_jackel_plugin_metadata_contract(self):
        manifest = self.load_json(MANIFEST_PATH)
        marketplace = self.load_json(MARKETPLACE_PATH)
        mcp_config = self.load_json(MCP_PATH)

        self.assertEqual(PLUGIN_ROOT.name, "jackel")
        self.assertEqual(manifest["name"], "jackel")
        entry = marketplace["plugins"]
        self.assertEqual(len(entry), 1)
        entry = entry[0]
        self.assert_marketplace_entry(entry)
        self.assertEqual(entry["name"], "jackel")
        self.assertEqual(entry["source"], {"source": "local", "path": "./plugins/jackel"})
        self.assertEqual(
            entry["policy"],
            {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        )
        self.assertEqual(entry["category"], "Productivity")
        self.assertEqual(marketplace["name"], "anubis-quantum-cipher")
        self.assertEqual(marketplace["interface"]["displayName"], "Anubis Quantum Cipher")

        interface = manifest["interface"]
        self.assertEqual(interface["displayName"], "JACKAL")
        self.assertEqual(interface["shortDescription"], "Claim-aware computation with explicit evidence classes")
        self.assertEqual(interface["developerName"], "Anubis Quantum Cipher")
        self.assertEqual(interface["category"], "Productivity")
        self.assertEqual(interface["capabilities"], ["Interactive"])
        self.assertEqual(interface["websiteURL"], "https://github.com/AnubisQuantumCipher/jackal")
        self.assertEqual(
            interface["defaultPrompt"],
            [
                "Classify and verify this numerical claim with JACKAL.",
                "Find the strongest supported bound and refuse any silent downgrade.",
                "Verify this receipt or claim bundle against my pinned expectations.",
                "Verify this Anubis Safe program-evidence package without executing its artifact.",
            ],
        )
        expected_long_description = (
            "Expose JACKAL's 41-tool v1.7.3 candidate runtime through Codex. "
            "The MCP adapter copies the parsed runtime result object into "
            "structuredContent unchanged; its only adapter-local tool result is "
            "status=refused reason=plugin-busy. Runtime result and assurance "
            "vocabulary: ok, exact, structural-exact, formal-bounded, bounded, "
            "checked, estimated, model-based, verified, "
            "verified-program-evidence, verified-program-receipt, indeterminate, "
            "and refused. Formal-bounded is limited to checker-admitted fragments; "
            "program evidence leaves construct-totality, source, and runtime "
            "residuals open. Requires Apple Silicon macOS and Python >=3.10 at "
            "/opt/homebrew/bin/python3 (install with brew install python)."
        )
        self.assertEqual(interface["longDescription"], expected_long_description)
        self.assertIn(f"- `interface.longDescription`: `{expected_long_description}`", DESIGN_PATH.read_text(encoding="utf-8"))

        self.assertRegex(manifest["version"], r"^0\.1\.0\+codex\.\d{14}$")
        self.assertEqual(manifest["description"], "Expose JACKAL's claim-aware computation, domain-pack, and program-evidence kernel to Codex.")
        self.assertEqual(manifest["author"], {"name": "Anubis Quantum Cipher", "url": "https://github.com/AnubisQuantumCipher"})
        self.assertEqual(manifest["homepage"], "https://github.com/AnubisQuantumCipher/jackal")
        self.assertEqual(manifest["repository"], "https://github.com/AnubisQuantumCipher/jackal")
        self.assertEqual(manifest["license"], "MIT")
        self.assertEqual(
            manifest["keywords"],
            ["jackel", "mathematics", "numerical-trust", "formal-verification", "evidence", "mcp"],
        )
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        for forbidden in (
            "apps",
            "hooks",
            "assets",
        ):
            self.assertNotIn(forbidden, manifest)
        for forbidden in (
            "privacyPolicyURL",
            "termsOfServiceURL",
            "brandColor",
            "composerIcon",
            "logo",
            "logoDark",
            "screenshots",
        ):
            self.assertNotIn(forbidden, interface)

        self.assertEqual(
            mcp_config,
            {
                "mcpServers": {
                    "jackel": {
                        "command": "/bin/zsh",
                        "args": ["./scripts/launch_mcp.zsh"],
                        "cwd": ".",
                        "env_vars": ["JACKAL_HOME"],
                        "tool_timeout_sec": 3700,
                    }
                }
            },
        )

        skill = SKILL_PATH.read_text(encoding="utf-8")
        frontmatter = self.parse_skill_frontmatter(skill)
        self.assertEqual(set(frontmatter), {"name", "description"})
        self.assertEqual(frontmatter["name"], "jackel")
        self.assertEqual(frontmatter["description"], APPROVED_SKILL_DESCRIPTION)
        for phrase in (
            "full tool inventory",
            "jackal_claim",
            "jackal_verify_bundle",
            "jackal_verify_receipt",
            "jackal_anubis_verify_program",
            "inventory-safe-v1",
            "policy-construct-totality-not-established",
            "None executes the compiled artifact",
            "direct tools remain available",
            "preserve every returned status/assumption/non-claim/residual/refusal verbatim",
            "never promote assurance or silently downgrade",
            "caller or separately trusted source, not evidence under review",
            "bundle/pin identity mismatch is a safety failure",
            "formal-bounded applies only to checker-admitted fragments",
            "Verification expectations are authorization, not data discovery",
            "integrate-bound-cert",
            "Select the assurance lane",
            "error estimate is not a bound",
            "Source-to-native refinement remains open and unclaimed",
            "Run a weaker lane only when the caller explicitly requests one",
            "Apple Silicon macOS only",
            "Do not bypass the Darwin/arm64 host guard",
            "Python >=3.10 at `/opt/homebrew/bin/python3`",
            "brew install python",
        ):
            self.assertIn(phrase, skill)

        known_text_paths = [MANIFEST_PATH, MCP_PATH, SKILL_PATH, MARKETPLACE_PATH]
        with tempfile.TemporaryDirectory() as temporary_directory:
            binary_path = Path(temporary_directory) / "future-binary-asset.bin"
            binary_path.write_bytes(b"\xff\x00\xfe")
            self.assert_no_placeholders(known_text_paths)

    def test_every_shipped_plugin_path_exists_and_is_identity_governed(self):
        manifest = self.load_json(MANIFEST_PATH)
        mcp = self.load_json(MCP_PATH)["mcpServers"]["jackel"]
        referenced = {
            "README.md",
            ".codex-plugin/plugin.json",
            manifest["mcpServers"].removeprefix("./"),
            "mcp/server.py",
            "scripts/provision_runtime.py",
            "scripts/launch_mcp.zsh",
            "scripts/verify_plugin.py",
            "skills/jackel/SKILL.md",
        }
        identity_paths = {
            line.split("  ", 1)[1]
            for line in IDENTITY_PATH.read_text(encoding="utf-8").splitlines()
        }
        self.assertEqual(identity_paths, referenced)
        for relative in referenced:
            self.assertTrue((PLUGIN_ROOT / relative).is_file(), relative)
        self.assertEqual(mcp["args"], ["./scripts/launch_mcp.zsh"])
        self.assertFalse(
            any(
                path.name.endswith(".tar.gz") or path.name.startswith("jackal-v")
                for path in PLUGIN_ROOT.iterdir()
            )
        )

    def test_readme_documents_candidate_install_discovery_and_boundaries(self):
        text = README_PATH.read_text(encoding="utf-8")
        for required in (
            "41-tool",
            "v1.7.3 candidate",
            "release/capability_inventory_v1.json",
            "/bin/zsh scripts/launch_mcp.zsh provision --tarball",
            "codex mcp list",
            "jackal_claim",
            "jackal_verify_receipt",
            "jackal_anubis_verify_program_receipt",
            "policy-construct-totality-not-established",
            "refused",
            "indeterminate",
            "No silent downgrade",
        ):
            self.assertIn(required, text, required)

    def test_launcher_uses_only_explicit_absolute_python_candidates_and_exact_flags(self):
        mcp = self.load_json(MCP_PATH)["mcpServers"]["jackel"]
        self.assertEqual(mcp["command"], "/bin/zsh")
        source = LAUNCHER_PATH.read_text(encoding="utf-8")
        self.assertIn("/opt/homebrew/bin/python3", source)
        self.assertIn("/usr/local/bin/python3", source)
        self.assertIn("/usr/bin/python3", source)
        for forbidden in ("command -v", "whence", "eval", "$PATH", "${PATH"):
            self.assertNotIn(forbidden, source)
        for required_probe in (
            "sys.version_info", "platform.system", "platform.machine", '"O_NOFOLLOW"',
            '"O_DIRECTORY"', '"access"', '"fstat"', '"lseek"', '"open"',
            '"read"', '"scandir"', '"stat"', '"waitid"', '"P_PID"',
            '"WEXITED"', '"WNOHANG"', '"WNOWAIT"', '"CLD_EXITED"',
            '"CLD_KILLED"', '"CLD_DUMPED"', '"killpg"',
            '"set_blocking"', '"socketpair"', "ctypes.CDLL",
            '"renameatx_np"', "selectors.DefaultSelector",
            "signal.setitimer", "signal.getitimer", "signal.ITIMER_REAL",
            "signal.SIGALRM", "tarfile.open", "urllib.request.urlopen",
            "is_absolute",
        ):
            self.assertIn(required_probe, source)
        self.assertIn('exec "$python" -I -S -B', source)

    def _run_rewritten_launcher(self, candidate_sources, *launcher_arguments):
        source = LAUNCHER_PATH.read_text(encoding="utf-8")
        marker = textwrap.dedent("""\
            PYTHON_CANDIDATES=(
              /opt/homebrew/bin/python3
              /usr/local/bin/python3
              /usr/bin/python3
            )
        """)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "plugin"
            scripts = root / "scripts"
            mcp = root / "mcp"
            scripts.mkdir(parents=True)
            mcp.mkdir()
            log = root / "calls.log"
            candidates = []
            for index, body in enumerate(candidate_sources):
                candidate = root / f"candidate-{index}"
                candidate.write_text(
                    "#!/bin/zsh\n"
                    f"export LAUNCHER_FIXTURE_LOG={str(log)!r}\n"
                    + body,
                    encoding="utf-8",
                )
                candidate.chmod(0o755)
                candidates.append(candidate)
            replacement = "PYTHON_CANDIDATES=(\n" + "".join(
                f"  {candidate}\n" for candidate in candidates
            ) + ")\n"
            self.assertIn(marker, source)
            (scripts / "launch_mcp.zsh").write_text(
                source.replace(marker, replacement), encoding="utf-8",
            )
            (mcp / "server.py").write_text("raise SystemExit(99)\n", encoding="utf-8")
            (scripts / "provision_runtime.py").write_text(
                "raise SystemExit(98)\n", encoding="utf-8",
            )
            completed = subprocess.run(
                ["/bin/zsh", str(scripts / "launch_mcp.zsh"), *launcher_arguments],
                cwd=root, capture_output=True, text=True, check=False,
                env={"PATH": "/definitely/not/a/python/path"}, timeout=2,
            )
            calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
            return completed, calls, root

    def test_launcher_simulates_capability_fallback_and_provision_mode(self):
        refusing = 'print -r -- "refused:$1:$2:$3:$4" >> "$LAUNCHER_FIXTURE_LOG"\nexit 17\n'
        accepting = textwrap.dedent("""\
            if [[ "$4" == "-c" ]]; then
              print -r -- "accepted:$1:$2:$3:$4" >> "$LAUNCHER_FIXTURE_LOG"
              exit 0
            fi
            print -r -- "accepted:$*" >> "$LAUNCHER_FIXTURE_LOG"
            exit 23
        """)
        completed, calls, root = self._run_rewritten_launcher(
            [refusing, accepting], "provision", "--check",
        )
        self.assertEqual(completed.returncode, 23)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0], "refused:-I:-S:-B:-c")
        self.assertEqual(calls[1], "accepted:-I:-S:-B:-c")
        self.assertEqual(
            calls[2],
            f"accepted:-I -S -B {root.resolve()}/scripts/provision_runtime.py --check",
        )
        self.assertFalse(any(root.rglob("*.pyc")))

    def test_launcher_refuses_once_with_126_when_no_candidate_passes(self):
        refusing = 'print -r -- "refused:$1:$2:$3:$4" >> "$LAUNCHER_FIXTURE_LOG"\nexit 17\n'
        completed, calls, unused_root = self._run_rewritten_launcher(
            [refusing, refusing],
        )
        self.assertEqual(completed.returncode, 126)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(
            completed.stderr,
            "jackal_mcp=refused reason=no-compatible-python requirement='Python >=3.10 at /opt/homebrew/bin/python3' recovery='brew install python'\n",
        )
        self.assertEqual(len(calls), 2)

    def test_hosted_macos_workflow_mechanically_runs_all_repo_local_plugin_gates(self):
        self.assertTrue(WORKFLOW_PATH.is_file(), "hosted JACKAL plugin workflow is missing")
        source = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("runs-on: macos-14", source)
        self.assertIn('test "$(uname -s)" = Darwin', source)
        self.assertIn('test "$(uname -m)" = arm64', source)
        self.assertIn(
            "/opt/homebrew/bin/python3 -B -m unittest discover -s tests/codex_plugin -v",
            source,
        )
        self.assertIn(
            "/opt/homebrew/bin/python3 -B plugins/jackel/scripts/verify_plugin.py",
            source,
        )
        self.assertIn(
            "/opt/homebrew/bin/python3 -B -m unittest tests.codex_plugin.test_plugin_metadata -v",
            source,
        )
        self.assertIn(
            "test_real_installed_config_smoke_without_runtime",
            source,
        )
        self.assertIn(
            "test_actual_plugin_installed_config_refuses_offline_without_runtime",
            source,
        )
        self.assertIn("PYTHONDONTWRITEBYTECODE: \"1\"", source)
        action_uses = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", source, re.MULTILINE)
        self.assertTrue(action_uses)
        for action in action_uses:
            with self.subTest(action=action):
                self.assertRegex(action, r"^[^@]+@[0-9a-f]{40}$")
        smoke_block = source.split("- name: Installed-config live smoke", 1)[1]
        for forbidden in (
            "brew install",
            "curl ",
            "urllib",
            "provision --",
            "release/download",
            "JACKAL_HOME=",
        ):
            self.assertNotIn(forbidden, smoke_block)

    def test_load_json_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            duplicate_json = Path(temporary_directory) / "duplicate.json"
            duplicate_json.write_text('{"nested": {"key": 1, "key": 2}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key: key"):
                self.load_json(duplicate_json)

    def test_marketplace_entry_contract_rejects_extra_and_product_keys(self):
        marketplace = self.load_json(MARKETPLACE_PATH)
        entry = marketplace["plugins"][0]

        with_extra_key = dict(entry, extra="not allowed")
        with self.assertRaises(AssertionError):
            self.assert_marketplace_entry(with_extra_key)

        with_entry_products = dict(entry, products=["gated"])
        with self.assertRaises(AssertionError):
            self.assert_marketplace_entry(with_entry_products)

        with_policy_products = dict(entry, policy=dict(entry["policy"], products=["gated"]))
        with self.assertRaises(AssertionError):
            self.assert_marketplace_entry(with_policy_products)

    def test_skill_frontmatter_rejects_malformed_or_duplicate_mappings(self):
        malformed_frontmatters = (
            "name: jackel\n---\n",
            "---\nname jackel\n---\n",
            "---\nname: jackel\nname: duplicate\n---\n",
            "---\nname: jackel\ndescription:\n---\n",
            "---\nname: jackel\ndescription: valid\n",
            "---\nname: jackel\ndescription: valid\nbroken: [\n---\n",
        )
        for malformed in malformed_frontmatters:
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                self.parse_skill_frontmatter(malformed)


if __name__ == "__main__":
    unittest.main()
