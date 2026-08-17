import base64
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from tests.codex_plugin import live_acceptance as live


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_TOOLS = REPOSITORY_ROOT / "plugin" / "hermes" / "tools.json"


def mcp_response(request_id, payload):
    text = json.dumps(
        payload, ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(",", ":"),
    )
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [{"type": "text", "text": text}],
            "structuredContent": copy.deepcopy(payload),
        },
    }


def formal_payload(emitted_at):
    certificate = b"jackal-int-cert v1\noutput 0 1\n"
    receipt = {
        "schema": "jackal-formal-receipt-v1",
        "variant": "int_cert",
        "release_epoch": "v1.7.0",
        "emitted_at_unix": emitted_at,
        "request": {
            "command": "integrate-bound-cert",
            "expression": "sin(x)",
            "input_lo": "0",
            "input_hi": "1",
            "tolerance": "1/100",
        },
        "result": {
            "status": "formal-bounded",
            "enclosure_lo": "0",
            "enclosure_hi": "1",
        },
        "certificate": {
            "schema": "jackal-int-cert v1",
            "bytes_b64": base64.b64encode(certificate).decode("ascii"),
            "sha256": hashlib.sha256(certificate).hexdigest(),
        },
        "identities": {
            "evaluator_sha256": live.INT_CERT_PRODUCER_SHA256,
            "producer_sha256": live.INT_CERT_PRODUCER_SHA256,
            "checker_sha256": live.INT_CERT_CHECKER_SHA256,
            "plugin_sha256": live.HERMES_BUNDLE_SHA256,
        },
        "theorem": {"id": "int_cert_sound"},
        "checker": {"verdict": "ACCEPT"},
    }
    receipt["receipt_digest_sha256"] = live.receipt_digest(receipt)
    return {"status": "formal-bounded", "checker_rerun": "ACCEPT", "receipt": receipt}


class IdentityAndInstallPlanTests(unittest.TestCase):
    def write_wrapper(self, root, version="0.1.0+codex.20260817170025"):
        (root / ".codex-plugin").mkdir(parents=True)
        (root / "mcp").mkdir()
        manifest_bytes = (
            json.dumps({"name": "jackel", "version": version}) + "\n"
        ).encode("utf-8")
        (root / ".codex-plugin" / "plugin.json").write_bytes(manifest_bytes)
        payload = b"wrapper bytes\n"
        (root / "mcp" / "server.py").write_bytes(payload)
        (root / "PLUGIN_IDENTITY.sha256").write_text(
            f"{hashlib.sha256(manifest_bytes).hexdigest()}  .codex-plugin/plugin.json\n"
            f"{hashlib.sha256(payload).hexdigest()}  mcp/server.py\n",
            encoding="utf-8",
        )

    def test_cache_copy_is_located_by_identity_not_semver_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            self.write_wrapper(source)
            expected = live.verify_wrapper(source)
            cache = root / "codex" / "plugins" / "cache" / \
                "anubis-quantum-cipher" / "jackel" / "opaque-snapshot"
            shutil.copytree(source, cache)

            self.assertEqual(
                live.locate_cache_copy(
                    root / "codex", source,
                    marketplace="anubis-quantum-cipher", plugin="jackel",
                    expected_aggregate=expected,
                ),
                cache,
            )

            (cache / "mcp" / "server.py").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(live.AcceptanceError, "verified cache copy"):
                live.locate_cache_copy(
                    root / "codex", source,
                    marketplace="anubis-quantum-cipher", plugin="jackel",
                    expected_aggregate=expected,
                )

    def test_cache_locator_refuses_ambiguous_valid_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            self.write_wrapper(source)
            expected = live.verify_wrapper(source)
            base = root / "codex" / "plugins" / "cache" / \
                "anubis-quantum-cipher" / "jackel"
            shutil.copytree(source, base / "snapshot-a")
            shutil.copytree(source, base / "snapshot-b")
            with self.assertRaisesRegex(live.AcceptanceError, "exactly one"):
                live.locate_cache_copy(
                    root / "codex", source,
                    marketplace="anubis-quantum-cipher", plugin="jackel",
                    expected_aggregate=expected,
                )

    def test_isolated_install_plan_never_targets_real_codex_home(self):
        with self.assertRaisesRegex(live.AcceptanceError, "actual CODEX_HOME"):
            live.build_codex_install_plan(
                codex_home=Path.home() / ".codex",
                repository_root=REPOSITORY_ROOT,
                codex_binary=Path("/usr/local/bin/codex"),
            )

        with tempfile.TemporaryDirectory() as directory:
            plan = live.build_codex_install_plan(
                codex_home=Path(directory), repository_root=REPOSITORY_ROOT,
                codex_binary=Path("/usr/local/bin/codex"),
            )
        self.assertEqual(plan.environment["CODEX_HOME"], directory)
        self.assertEqual(
            [command[1:] for command in plan.commands],
            [
                ("plugin", "marketplace", "add", str(REPOSITORY_ROOT), "--json"),
                ("plugin", "add", "jackel@anubis-quantum-cipher", "--json"),
                ("plugin", "list", "--available", "--json"),
            ],
        )

    def test_codex_install_requires_list_to_confirm_enabled_installed_plugin(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = live.build_codex_install_plan(
                codex_home=Path(directory), repository_root=REPOSITORY_ROOT,
                codex_binary=Path("/usr/local/bin/codex"),
            )

            outputs = iter([
                {"installedRoot": str(REPOSITORY_ROOT)},
                {"pluginId": "jackel@anubis-quantum-cipher"},
                {"installed": []},
            ])

            def runner(command, **kwargs):
                return subprocess.CompletedProcess(
                    command, 0, json.dumps(next(outputs)), "",
                )

            with self.assertRaisesRegex(live.AcceptanceError, "installed plugin"):
                live.execute_codex_install(plan, runner=runner)


class AcceptanceValidationTests(unittest.TestCase):
    def test_caller_pins_are_independent_canonical_constants(self):
        self.assertEqual(
            live.DEFAULT_POLICY_SHA256,
            "3ef0655ad2a3f9b553f7c4b9f7af2d4cfdd71c150f4a0337b0da0cea32fd8410",
        )
        self.assertEqual(
            live.canonical_sha256(live.EXPECTED_ROOT_PROPOSITION),
            "e6740fdaa34c63f07b037dd131191b92a8420ea902515cbfab94e9073f1ca269",
        )
        hostile_bundle = {
            "release_epoch": "forged",
            "policy": {"forged": True},
            "nodes": [{"proposition": {"forged": True}}],
        }
        arguments = live.claim_verification_arguments(hostile_bundle)
        self.assertIs(arguments["bundle"], hostile_bundle)
        self.assertEqual(arguments["expected_release_epoch"], "v1.6.0")
        self.assertEqual(arguments["expected_policy_sha256"], live.DEFAULT_POLICY_SHA256)
        self.assertEqual(arguments["expected_root_proposition"], live.EXPECTED_ROOT_PROPOSITION)
        self.assertEqual(arguments["verification_time_unix"], "1786752000")
        self.assertEqual(arguments["expected_nonce"], "jackal-codex-task5-v1")

    def test_exact_result_requires_strict_direct_parity(self):
        payload = {
            "status": "exact", "lane": "rat", "formal": False,
            "fields": {"exact": "3/10"},
        }
        live.validate_exact(mcp_response("exact", payload), copy.deepcopy(payload))
        mismatch = copy.deepcopy(payload)
        mismatch["fields"]["exact"] = "0.30000000000000004"
        with self.assertRaisesRegex(live.AcceptanceError, "direct backend parity"):
            live.validate_exact(mcp_response("exact", payload), mismatch)

    def test_formal_result_verifies_identities_digests_and_only_normalizes_time(self):
        mcp = formal_payload(10)
        direct = formal_payload(11)
        live.validate_formal_int_cert(mcp_response("formal", mcp), direct)

        tampered = formal_payload(11)
        tampered["receipt"]["certificate"]["sha256"] = "0" * 64
        tampered["receipt"]["receipt_digest_sha256"] = live.receipt_digest(
            tampered["receipt"]
        )
        with self.assertRaisesRegex(live.AcceptanceError, "certificate digest"):
            live.validate_formal_int_cert(mcp_response("formal", mcp), tampered)

    def test_named_formal_refusal_has_no_downgrade_shape(self):
        refused = {
            "status": "refused", "reason": "producer-refused",
            "detail": "operator exp is outside the int-cert fragment",
        }
        live.validate_unsupported_formal(
            mcp_response("refuse", refused), copy.deepcopy(refused)
        )
        leaked = dict(refused, lane="integrate-bound", formal=False)
        with self.assertRaisesRegex(live.AcceptanceError, "refusal shape"):
            live.validate_unsupported_formal(mcp_response("refuse", leaked), leaked)

    def test_receipt_replay_uses_fixed_int_cert_request(self):
        receipt = formal_payload(10)["receipt"]
        arguments = live.receipt_verification_arguments(receipt)
        self.assertIs(arguments["receipt"], receipt)
        self.assertEqual(
            {key: value for key, value in arguments.items() if key != "receipt"},
            {
                "expected_release_epoch": "v1.7.0",
                "expected_command": "integrate-bound-cert",
                "expected_expression": "sin(x)",
                "expected_input_lo": "0",
                "expected_input_hi": "1",
                "expected_tolerance": "1/100",
            },
        )


class MCPClientTests(unittest.TestCase):
    def test_close_bounds_final_wait_and_always_closes_streams(self):
        client = object.__new__(live.MCPClient)
        process = mock.Mock(pid=424242)
        process.wait.side_effect = (
            subprocess.TimeoutExpired("fixture", 2),
            subprocess.TimeoutExpired("fixture", 1),
            subprocess.TimeoutExpired("fixture", 2),
        )
        client._process = process
        client._stderr = mock.Mock()

        with (
            mock.patch.object(live.os, "killpg") as kill_group,
            self.assertRaises(live.AcceptanceError),
        ):
            client.close()

        self.assertEqual(
            kill_group.call_args_list,
            [mock.call(process.pid, live.signal.SIGTERM), mock.call(process.pid, live.signal.SIGKILL)],
        )
        process.stdout.close.assert_called_once_with()
        client._stderr.close.assert_called_once_with()

    def test_context_exit_preserves_an_existing_acceptance_failure(self):
        client = object.__new__(live.MCPClient)
        client.close = mock.Mock(side_effect=live.AcceptanceError("cleanup failed"))
        existing = live.AcceptanceError("acceptance failed first")

        client.__exit__(live.AcceptanceError, existing, None)

        client.close.assert_called_once_with()

    def test_installed_mcp_client_uses_exact_installed_config_not_current_python(self):
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory).resolve() / "installed"
            installed.mkdir()
            configured_command = "/absolute/configured/zsh"
            configured_args = ["./scripts/launch_mcp.zsh", "fixture-argument"]
            (installed / ".mcp.json").write_text(
                json.dumps({
                    "mcpServers": {
                        "jackel": {
                            "command": configured_command,
                            "args": configured_args,
                            "cwd": ".",
                            "env_vars": ["JACKAL_HOME"],
                            "tool_timeout_sec": 3700,
                        }
                    }
                }) + "\n",
                encoding="utf-8",
            )
            environment = {"CODEX_HOME": str(installed.parent), "JACKAL_HOME": "/runtime"}

            with mock.patch.object(live, "MCPClient", autospec=True) as client:
                returned = live.installed_mcp_client(installed, environment)

            self.assertIs(returned, client.return_value)
            client.assert_called_once_with(
                [configured_command, *configured_args],
                cwd=installed,
                environment=environment,
            )
            self.assertNotEqual(configured_command, sys.executable)

    def test_installed_mcp_config_rejects_relative_command_or_escaping_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory).resolve() / "installed"
            installed.mkdir()
            base = {
                "mcpServers": {
                    "jackel": {
                        "command": "/bin/zsh",
                        "args": ["./scripts/launch_mcp.zsh"],
                        "cwd": ".",
                        "env_vars": ["JACKAL_HOME"],
                        "tool_timeout_sec": 3700,
                    }
                }
            }
            for command, cwd in (("python3", "."), ("/bin/zsh", "..")):
                with self.subTest(command=command, cwd=cwd):
                    document = copy.deepcopy(base)
                    record = document["mcpServers"]["jackel"]
                    record["command"] = command
                    record["cwd"] = cwd
                    (installed / ".mcp.json").write_text(
                        json.dumps(document) + "\n", encoding="utf-8",
                    )
                    with self.assertRaises(live.AcceptanceError):
                        live.installed_mcp_client(installed, {})

    def test_real_line_protocol_correlates_requests_around_notification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "server.py"
            server.write_text(textwrap.dedent("""\
                import json
                import sys

                for line in sys.stdin:
                    message = json.loads(line)
                    if "id" not in message:
                        continue
                    response = {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": {"method": message["method"]},
                    }
                    print(json.dumps(response, sort_keys=True), flush=True)
            """), encoding="utf-8")
            with live.MCPClient(
                [sys.executable, str(server)], cwd=root,
                environment=os.environ, timeout=2,
            ) as client:
                first = client.request("one", "initialize", {})
                client.notification("notifications/initialized", {})
                second = client.request("two", "tools/list", {})
        self.assertEqual(first["result"], {"method": "initialize"})
        self.assertEqual(second["result"], {"method": "tools/list"})


class ScriptedClient:
    def __init__(self, runtime_document):
        self.runtime_document = runtime_document
        self.calls = []
        self.formal = formal_payload(10)
        root_node = {
            "id": "root-node",
            "proposition": copy.deepcopy(live.EXPECTED_ROOT_PROPOSITION),
        }
        self.bundle = {
            "release_epoch": "v1.6.0",
            "policy": copy.deepcopy(live.DEFAULT_POLICY),
            "root": "root-node",
            "nodes": [root_node],
        }

    def request(self, request_id, method, params):
        if method == "initialize":
            return {
                "jsonrpc": "2.0", "id": request_id,
                "result": {
                    "protocolVersion": live.MCP_PROTOCOL_VERSION,
                    "serverInfo": {"name": "jackel-codex", "version": "0.1.0"},
                    "capabilities": {"tools": {"listChanged": False}},
                },
            }
        if method == "tools/list":
            return {
                "jsonrpc": "2.0", "id": request_id,
                "result": {"tools": [
                    {"name": record["name"]}
                    for record in self.runtime_document["tools"]
                ]},
            }
        self.assert_tools_call(method)
        name = params["name"]
        self.calls.append((name, copy.deepcopy(params["arguments"])))
        if name == "jackal_exact":
            payload = {
                "status": "exact", "lane": "rat", "formal": False,
                "fields": {"exact": "3/10"},
            }
        elif name == "jackal_integrate_bound_cert" and \
                params["arguments"]["expression"] == "sin(x)":
            payload = self.formal
        elif name == "jackal_integrate_bound_cert":
            payload = {
                "status": "refused", "reason": "producer-refused",
                "detail": "outside fragment",
            }
        elif name == "jackal_claim":
            payload = {
                "status": "ok", "root": "root-node",
                "bundle_digest_sha256": "a" * 64,
                "route_trace": [{"selected": "engine-exact-cert"}],
                "bundle": self.bundle,
            }
        elif name == "jackal_verify_bundle":
            payload = {
                "status": "verified", "verdict": "verified",
                "report": [
                    "claim-verify=verified",
                    "root.proposition_sha256=" + live.EXPECTED_ROOT_PROPOSITION_SHA256,
                    "freshness: epoch=v1.6.0 environment=fixture nonce=bound",
                ],
            }
        elif name == "jackal_verify_receipt":
            receipt = self.formal["receipt"]
            payload = {
                "status": "verified", "verdict": "ACCEPT",
                "receipt_digest_sha256": receipt["receipt_digest_sha256"],
                "certificate_sha256": receipt["certificate"]["sha256"],
                "checker_sha256": live.INT_CERT_CHECKER_SHA256,
                "evaluator_sha256": live.INT_CERT_PRODUCER_SHA256,
                "plugin_sha256": live.HERMES_BUNDLE_SHA256,
                "enclosure": ["0", "1"],
            }
        else:
            raise AssertionError(name)
        return mcp_response(request_id, payload)

    def notification(self, method, params):
        self.calls.append((method, copy.deepcopy(params)))

    def assert_tools_call(self, method):
        if method != "tools/call":
            raise AssertionError(method)


class AcceptanceOrchestrationTests(unittest.TestCase):
    def test_full_strict_sequence_has_no_weaker_fallback(self):
        runtime_document = json.loads(RUNTIME_TOOLS.read_text(encoding="utf-8"))
        client = ScriptedClient(runtime_document)
        direct_calls = []

        def direct(tool, arguments):
            direct_calls.append((tool, copy.deepcopy(arguments)))
            if tool == "jackal_exact":
                return {
                    "status": "exact", "lane": "rat", "formal": False,
                    "fields": {"exact": "3/10"},
                }
            if arguments["expression"] == "sin(x)":
                return formal_payload(11)
            return {
                "status": "refused", "reason": "producer-refused",
                "detail": "outside fragment",
            }

        report = live.run_acceptance(
            client=client, runtime_document=runtime_document,
            direct_call=direct,
        )
        tool_calls = [name for name, _ in client.calls if not name.startswith("notifications/")]
        self.assertEqual(
            tool_calls,
            [
                "jackal_exact", "jackal_integrate_bound_cert",
                "jackal_integrate_bound_cert", "jackal_claim",
                "jackal_verify_bundle", "jackal_verify_receipt",
            ],
        )
        self.assertNotIn("jackal_integrate_bound", tool_calls)
        self.assertEqual(
            [name for name, _ in direct_calls],
            ["jackal_exact", "jackal_integrate_bound_cert", "jackal_integrate_bound_cert"],
        )
        self.assertEqual(report["discovered_tool_count"], 34)
        self.assertEqual(report["gates"], {
            "exact": "exact", "formal": "formal-bounded",
            "unsupported_formal": "producer-refused",
            "claim_bundle": "verified", "formal_receipt": "verified",
        })


if __name__ == "__main__":
    unittest.main()
