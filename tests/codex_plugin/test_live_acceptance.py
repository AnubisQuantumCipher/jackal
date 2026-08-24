import base64
import copy
import hashlib
import io
import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
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
        "release_epoch": live.FORMAL_RELEASE_EPOCH,
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
    def test_formal_receipt_oracle_matches_current_hermes_bundle_pin(self):
        row = next(
            (
                line.split()
                for line in (REPOSITORY_ROOT / "release/MANIFEST.sha256")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.startswith("plugin_hermes ")
            ),
            None,
        )
        self.assertIsNotNone(row, "release manifest has no plugin_hermes row")
        self.assertEqual(live.HERMES_BUNDLE_SHA256, row[-1])

    def test_dry_run_lists_each_mcp_tool_once(self):
        document = live.dry_run_document(
            codex_binary=Path("/absolute/codex"),
            repository_root=REPOSITORY_ROOT,
        )
        tools = document["mcp_tools"]
        self.assertEqual(len(tools), len(set(tools)))

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

    def test_cache_locator_refuses_any_same_version_unverified_sibling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            self.write_wrapper(source)
            expected = live.verify_wrapper(source)
            base = root / "codex" / "plugins" / "cache" / \
                "anubis-quantum-cipher" / "jackel"
            shutil.copytree(source, base / "verified")
            shutil.copytree(source, base / "tampered")
            (base / "tampered" / "mcp" / "server.py").write_text(
                "tampered\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(live.AcceptanceError, "unverified cache copy"):
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
        self.assertEqual(plan.environment["CODEX_HOME"], str(Path(directory).resolve()))
        self.assertEqual(
            [command[1:] for command in plan.commands],
            [
                ("plugin", "marketplace", "add", str(REPOSITORY_ROOT), "--json"),
                ("plugin", "add", "jackel@anubis-quantum-cipher", "--json"),
                ("plugin", "list", "--available", "--json"),
            ],
        )

    def test_isolated_install_refuses_real_home_symlink_alias_before_runner(self):
        runner = mock.Mock()
        with tempfile.TemporaryDirectory() as directory:
            alias = Path(directory) / "codex-home-alias"
            alias.symlink_to(Path.home() / ".codex", target_is_directory=True)
            with self.assertRaisesRegex(live.AcceptanceError, "actual CODEX_HOME"):
                plan = live.build_codex_install_plan(
                    codex_home=alias,
                    repository_root=REPOSITORY_ROOT,
                    codex_binary=Path("/usr/local/bin/codex"),
                )
                live.execute_codex_install(plan, runner=runner)
        runner.assert_not_called()

    def test_isolated_install_uses_account_home_even_when_home_is_forged(self):
        runner = mock.Mock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            account_home = root / "account-home"
            account_home.mkdir()
            account_codex_home = account_home / ".codex"
            account_codex_home.mkdir()
            forged_home = root / "forged-home"
            forged_home.mkdir()
            safe_home = root / "safe-codex-home"
            safe_home.mkdir()
            account_entry = mock.Mock(pw_dir=str(account_home))
            with (
                mock.patch.object(live.pwd, "getpwuid", return_value=account_entry),
                mock.patch.dict(os.environ, {"HOME": str(forged_home)}),
            ):
                with self.assertRaisesRegex(live.AcceptanceError, "actual CODEX_HOME"):
                    live.build_codex_install_plan(
                        codex_home=account_codex_home,
                        repository_root=REPOSITORY_ROOT,
                        codex_binary=Path("/usr/local/bin/codex"),
                    )

            with (
                mock.patch.object(live.pwd, "getpwuid", return_value=account_entry),
                mock.patch.dict(os.environ, {"HOME": str(forged_home)}),
            ):
                plan = live.build_codex_install_plan(
                    codex_home=safe_home,
                    repository_root=REPOSITORY_ROOT,
                    codex_binary=Path("/usr/local/bin/codex"),
                )
                hostile_environment = dict(plan.environment)
                hostile_environment["CODEX_HOME"] = str(account_codex_home)
                hostile_plan = live.CodexInstallPlan(
                    commands=plan.commands,
                    environment=hostile_environment,
                    forbidden_codex_homes=getattr(plan, "forbidden_codex_homes", ()),
                )
                with self.assertRaisesRegex(
                    live.AcceptanceError, "actual CODEX_HOME"
                ):
                    live.execute_codex_install(hostile_plan, runner=runner)

        runner.assert_not_called()

    def test_isolated_install_refuses_account_home_ancestors_and_descendants(self):
        account_codex_home = (Path.home() / ".codex").resolve(strict=False)
        for overlapping in (account_codex_home.parent, account_codex_home / "nested"):
            with self.subTest(overlapping=overlapping):
                with self.assertRaisesRegex(live.AcceptanceError, "actual CODEX_HOME"):
                    live.build_codex_install_plan(
                        codex_home=overlapping,
                        repository_root=REPOSITORY_ROOT,
                        codex_binary=Path("/usr/local/bin/codex"),
                    )

    def test_isolated_install_refuses_symlinked_tmpdir_inside_account_state(self):
        runner = mock.Mock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            account_home = root / "account"
            account_codex_home = account_home / ".codex"
            account_codex_home.mkdir(parents=True)
            tmp_alias = root / "hostile-tmp"
            tmp_alias.symlink_to(account_codex_home, target_is_directory=True)
            selected = tmp_alias / "nested-isolation"
            selected.mkdir()
            account_record = type("Account", (), {"pw_dir": str(account_home)})()
            with mock.patch.object(
                live.pwd, "getpwuid", return_value=account_record
            ):
                with self.assertRaisesRegex(live.AcceptanceError, "actual CODEX_HOME"):
                    live.build_codex_install_plan(
                        codex_home=selected,
                        repository_root=REPOSITORY_ROOT,
                        codex_binary=Path("/usr/local/bin/codex"),
                    )

                safe = root / "safe-isolation"
                safe.mkdir()
                plan = live.build_codex_install_plan(
                    codex_home=safe,
                    repository_root=REPOSITORY_ROOT,
                    codex_binary=Path("/usr/local/bin/codex"),
                )
                hostile_environment = dict(plan.environment)
                hostile_environment["CODEX_HOME"] = str(selected.resolve())
                hostile_plan = live.CodexInstallPlan(
                    commands=plan.commands,
                    environment=hostile_environment,
                    forbidden_codex_homes=plan.forbidden_codex_homes,
                )
                with self.assertRaisesRegex(
                    live.AcceptanceError, "actual CODEX_HOME"
                ):
                    live.execute_codex_install(hostile_plan, runner=runner)

        runner.assert_not_called()

    def test_isolated_install_revalidates_home_before_every_runner_call(self):
        runner_calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            selected = root / "codex-home"
            selected.mkdir()
            replacement = root / "original-codex-home"
            plan = live.build_codex_install_plan(
                codex_home=selected,
                repository_root=REPOSITORY_ROOT,
                codex_binary=Path("/usr/local/bin/codex"),
            )

            def runner(command, **unused):
                runner_calls.append(tuple(command))
                if len(runner_calls) == 1:
                    selected.rename(replacement)
                    selected.symlink_to(
                        Path.home() / ".codex", target_is_directory=True
                    )
                return subprocess.CompletedProcess(command, 0, "{}", "")

            try:
                with self.assertRaisesRegex(
                    live.AcceptanceError, "actual CODEX_HOME|canonical directory"
                ):
                    live.execute_codex_install(plan, runner=runner)
            finally:
                if selected.is_symlink():
                    selected.unlink()
                if replacement.exists():
                    replacement.rename(selected)

        self.assertEqual(len(runner_calls), 1)

    def test_install_execution_requires_canonical_nonsymlink_codex_home(self):
        runner = mock.Mock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            alias = root / "alias"
            alias.symlink_to(target, target_is_directory=True)
            plan = live.CodexInstallPlan(
                commands=(("/absolute/codex", "plugin", "list", "--json"),),
                environment={"CODEX_HOME": str(alias)},
            )
            with self.assertRaisesRegex(live.AcceptanceError, "canonical directory"):
                live.execute_codex_install(plan, runner=runner)
        runner.assert_not_called()

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
        self.assertEqual(live.FORMAL_RELEASE_EPOCH, "v1.7.2")
        receipt = formal_payload(10)["receipt"]
        arguments = live.receipt_verification_arguments(receipt)
        self.assertIs(arguments["receipt"], receipt)
        self.assertEqual(
            {key: value for key, value in arguments.items() if key != "receipt"},
            {
                "expected_release_epoch": live.FORMAL_RELEASE_EPOCH,
                "expected_command": "integrate-bound-cert",
                "expected_expression": "sin(x)",
                "expected_input_lo": "0",
                "expected_input_hi": "1",
                "expected_tolerance": "1/100",
            },
        )


class MCPClientTests(unittest.TestCase):
    def test_runtime_acceptance_environment_is_provisioner_owned(self):
        hostile = {
            "PATH": "/tmp/hostile",
            "PYTHONPATH": "/tmp/inject",
            "PYTHONHOME": "/tmp/inject-home",
            "DYLD_INSERT_LIBRARIES": "/tmp/inject.dylib",
            "HOME": "/tmp/fake-home",
            "CODEX_HOME": "/tmp/fake-codex",
            "JACKAL_HOME": "/tmp/stale-runtime",
        }
        runtime = Path("/absolute/pinned-runtime")

        result = live.runtime_acceptance_environment(runtime, hostile)

        self.assertEqual(result["JACKAL_HOME"], str(runtime))
        self.assertEqual(
            result["PATH"],
            f"{Path(sys.executable).parent}:/usr/bin:/bin:/usr/sbin:/sbin",
        )
        self.assertEqual(set(result), {"PATH", "JACKAL_HOME"})

    def test_direct_backend_receives_exact_sanitized_environment(self):
        environment = {
            "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin:/usr/sbin:/sbin",
            "JACKAL_HOME": "/absolute/pinned-runtime",
        }
        completed = subprocess.CompletedProcess(
            [], 0, '{"status":"exact"}\n', ""
        )
        with mock.patch.object(live.subprocess, "run", return_value=completed) as runner:
            result = live.direct_backend_call(
                Path("/absolute/pinned-runtime"),
                "jackal_exact",
                {"expression": "1+1"},
                environment=environment,
            )

        self.assertEqual(result, {"status": "exact"})
        self.assertEqual(runner.call_args.kwargs["env"], environment)
        self.assertIsNot(runner.call_args.kwargs["env"], environment)

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

    def test_real_installed_config_smoke_without_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory).resolve() / "installed"
            installed.mkdir()
            server = installed / "fixture_server.py"
            server.write_text(textwrap.dedent("""\
                import json
                import sys

                for line in sys.stdin:
                    message = json.loads(line)
                    if "id" not in message:
                        continue
                    method = message["method"]
                    if method == "initialize":
                        result = {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {"tools": {"listChanged": False}},
                            "serverInfo": {"name": "fixture", "version": "1"},
                        }
                    elif method == "tools/list":
                        result = {"tools": []}
                    else:
                        result = {}
                    print(json.dumps({
                        "jsonrpc": "2.0", "id": message["id"], "result": result,
                    }), flush=True)
            """), encoding="utf-8")
            (installed / ".mcp.json").write_text(json.dumps({
                "mcpServers": {
                    "jackel": {
                        "command": sys.executable,
                        "args": ["-B", "./fixture_server.py"],
                        "cwd": ".",
                        "env_vars": ["JACKAL_HOME"],
                        "tool_timeout_sec": 3700,
                    }
                }
            }) + "\n", encoding="utf-8")
            environment = {"PYTHONDONTWRITEBYTECODE": "1"}

            with live.installed_mcp_client(installed, environment) as client:
                initialized = client.request("init", "initialize", {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "ci-smoke", "version": "1"},
                })
                client.notification("notifications/initialized", {})
                listed = client.request("list", "tools/list", {})

            self.assertEqual(initialized["result"]["serverInfo"]["name"], "fixture")
            self.assertEqual(listed["result"], {"tools": []})
            self.assertFalse(any(installed.rglob("*.pyc")))

    def test_actual_plugin_installed_config_refuses_offline_without_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            installed = root / "installed"
            shutil.copytree(live.PLUGIN_ROOT, installed)
            absent_runtime = root / "absent-runtime"
            environment = live.runtime_acceptance_environment(
                absent_runtime,
                {"JACKAL_HOME": str(absent_runtime)},
            )

            with live.installed_mcp_client(installed, environment) as client:
                with self.assertRaisesRegex(
                    live.AcceptanceError, r"closed std(?:in|out)"
                ):
                    client.request("init", "initialize", {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "ci-offline-smoke", "version": "1"},
                    })

            self.assertFalse(absent_runtime.exists())
            self.assertFalse(any(installed.rglob("__pycache__")))
            self.assertFalse(any(installed.rglob("*.pyc")))

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


class HostDiscoveryAcceptanceTests(unittest.TestCase):
    def plan(self):
        return live.build_host_discovery_plan(
            codex_binary=Path("/absolute/codex"),
            codex_home=Path("/absolute/codex-home"),
            runtime_root=Path("/absolute/runtime"),
            nonce="host-proof-nonce-0123456789abcdef",
            emitted_at_unix="1786752000",
        )

    def event_bytes(self, plan):
        request = live.host_claim_request(plan)
        bundle = {
            "schema": "jackal-claim-bundle-v1",
            "release_epoch": live.CLAIM_RELEASE_EPOCH,
            "engine_identity": {
                "evaluator_sha256": "e" * 64,
                "source_anb_sha256": "a" * 64,
            },
            "registries": {
                "inference_registry_sha256": "1" * 64,
                "unit_registry_sha256": "2" * 64,
            },
            "policy": copy.deepcopy(live.DEFAULT_POLICY),
            "nodes": [{
                "id": "root-node",
                "proposition": copy.deepcopy(live.EXPECTED_ROOT_PROPOSITION),
            }],
            "root": "root-node",
            "rendering": {
                "token": "render-v1/exact/fixture",
                "permitted_text": "fixture verified rendering",
            },
        }
        bundle["bundle_digest_sha256"] = live.canonical_sha256(bundle)
        claim_arguments = {"request": request}
        claim_result = {
            "status": "ok",
            "root": "root-node",
            "bundle_digest_sha256": bundle["bundle_digest_sha256"],
            "rendering": copy.deepcopy(bundle["rendering"]),
            "route_trace": [{"lane": "exact", "selected": "engine-exact-cert"}],
            "bundle": bundle,
        }
        verify_arguments = live.host_verification_arguments(bundle, plan)
        verify_result = {
            "status": "verified",
            "verdict": "verified",
            "report": [
                "claim-verify=verified",
                "bundle.digest=" + bundle["bundle_digest_sha256"],
                "root.proposition_sha256=" + live.EXPECTED_ROOT_PROPOSITION_SHA256,
                "freshness: epoch=" + live.CLAIM_RELEASE_EPOCH
                + " environment=host nonce=bound",
            ],
        }

        def mcp_result(value):
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps(
                        value, sort_keys=True, separators=(",", ":")
                    ),
                }],
                "structured_content": value,
            }

        events = [
            {"type": "thread.started", "thread_id": "thread-fixture"},
            {"type": "turn.started"},
            {"type": "item.started", "item": {
                "id": "claim-id", "type": "mcp_tool_call", "server": "jackel",
                "tool": "jackal_claim", "arguments": claim_arguments,
                "status": "in_progress", "result": None, "error": None,
            }},
            {"type": "item.completed", "item": {
                "id": "claim-id", "type": "mcp_tool_call", "server": "jackel",
                "tool": "jackal_claim", "arguments": claim_arguments,
                "status": "completed", "error": None,
                "result": mcp_result(claim_result),
            }},
            {"type": "item.started", "item": {
                "id": "verify-id", "type": "mcp_tool_call", "server": "jackel",
                "tool": "jackal_verify_bundle", "arguments": verify_arguments,
                "status": "in_progress", "result": None, "error": None,
            }},
            {"type": "item.completed", "item": {
                "id": "verify-id", "type": "mcp_tool_call", "server": "jackel",
                "tool": "jackal_verify_bundle", "arguments": verify_arguments,
                "status": "completed", "error": None,
                "result": mcp_result(verify_result),
            }},
            {"type": "item.completed", "item": {
                "id": "summary-id", "type": "agent_message", "text": "verified",
            }},
            {"type": "turn.completed", "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 20,
                "output_tokens": 40,
            }},
        ]
        return b"".join(
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            for event in events
        )

    def registry_bytes(self, installed):
        return json.dumps([
            {
                "name": "jackel",
                "enabled": True,
                "disabled_reason": None,
                "transport": {
                    "type": "stdio",
                    "command": "/bin/zsh",
                    "args": ["./scripts/launch_mcp.zsh"],
                    "env": None,
                    "env_vars": ["JACKAL_HOME"],
                    "cwd": str(installed / "."),
                },
                "startup_timeout_sec": None,
                "tool_timeout_sec": 3700.0,
                "auth_status": "unsupported",
            }
        ], separators=(",", ":")).encode()

    def test_host_binary_identity_binds_canonical_bytes_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "codex-real"
            target.write_bytes(b"fixture codex binary v1")
            target.chmod(0o755)
            binary = root / "codex"
            binary.symlink_to(target)
            runner = mock.Mock(return_value=subprocess.CompletedProcess(
                (str(target), "--version"),
                0,
                b"codex-cli 0.146.0\n",
                b"",
            ))

            identity = live.inspect_host_binary(
                binary, runner=runner, environment={}
            )

            self.assertEqual(identity.invocation_path, str(binary))
            self.assertEqual(identity.resolved_path, str(target.resolve()))
            self.assertEqual(identity.sha256, hashlib.sha256(target.read_bytes()).hexdigest())
            self.assertEqual(identity.version, "codex-cli 0.146.0")
            runner.assert_called_once()
            self.assertEqual(
                runner.call_args.args[0], (str(target.resolve()), "--version")
            )

            target.write_bytes(b"fixture codex binary v2")
            target.chmod(0o755)
            changed = live.inspect_host_binary(
                binary, runner=runner, environment={}
            )
            self.assertNotEqual(changed.sha256, identity.sha256)

    def test_host_prompt_is_protocol_bound_and_command_allows_private_runtime(self):
        plan = self.plan()
        lowered = plan.prompt.lower()
        for forbidden in (
            "jackel", "mcp", "tool", "jackal_claim", "jackal_verify_bundle"
        ):
            self.assertNotIn(forbidden, lowered)
        self.assertIn(plan.nonce, plan.prompt)
        self.assertIn(plan.emitted_at_unix, plan.prompt)
        self.assertIn(
            live.canonical_bytes(live.host_claim_request(plan)).decode("utf-8"),
            plan.prompt,
        )
        self.assertEqual(plan.command[0], "/absolute/codex")
        self.assertEqual(
            plan.command[1:6],
            ("--ask-for-approval", "never", "exec", "--ephemeral", "--json"),
        )
        self.assertEqual(plan.command.count("--ask-for-approval"), 1)
        self.assertIn("danger-full-access", plan.command)
        self.assertNotIn("read-only", plan.command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", plan.command)
        self.assertNotIn("resume", plan.command)
        self.assertEqual(plan.command[-1], plan.prompt)

    def test_host_event_stream_accepts_known_preturn_diagnostics_only(self):
        plan = self.plan()
        events = [json.loads(line) for line in self.event_bytes(plan).splitlines()]
        events.insert(1, {
            "type": "item.completed",
            "item": {
                "id": "startup-warning",
                "type": "error",
                "message": (
                    "Skill descriptions were shortened to fit the 2% skills "
                    "context budget."
                ),
            },
        })
        events.insert(3, {
            "type": "item.completed",
            "item": {
                "id": "skills-warning",
                "type": "error",
                "message": (
                    "Skill descriptions were shortened to fit the 2% skills "
                    "context budget."
                ),
            },
        })
        raw = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in events
        )
        report = live.validate_host_discovery_events(raw, plan)
        self.assertEqual(report["tool_call_ids"], ["claim-id", "verify-id"])

        events[3]["item"]["message"] = "MCP startup failed"
        unknown = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in events
        )
        with self.assertRaisesRegex(live.AcceptanceError, "startup diagnostic"):
            live.validate_host_discovery_events(unknown, plan)

    def test_host_event_stream_requires_real_bound_mcp_lifecycle(self):
        plan = self.plan()
        raw = self.event_bytes(plan)

        report = live.validate_host_discovery_events(raw, plan)

        self.assertEqual(report["thread_id"], "thread-fixture")
        self.assertEqual(report["tool_call_ids"], ["claim-id", "verify-id"])
        self.assertEqual(
            report["transcript_sha256"], hashlib.sha256(raw).hexdigest()
        )
        summary_only = (
            b'{"type":"thread.started","thread_id":"thread-fixture"}\n'
            b'{"type":"turn.started"}\n'
            b'{"type":"item.completed","item":{"id":"summary-id",'
            b'"type":"agent_message",'
            b'"text":"verified"}}\n'
            b'{"type":"turn.completed","usage":{"input_tokens":1,'
            b'"cached_input_tokens":0,"output_tokens":1}}\n'
        )
        with self.assertRaisesRegex(live.AcceptanceError, "MCP lifecycle"):
            live.validate_host_discovery_events(summary_only, plan)

        stale = raw.replace(plan.nonce.encode(), b"stale-host-proof-nonce")
        with self.assertRaises(live.AcceptanceError):
            live.validate_host_discovery_events(stale, plan)

        events = [json.loads(line) for line in raw.splitlines()]
        events.insert(-1, {"type": "turn.failed", "error": {"message": "fixture"}})
        failed_turn = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in events
        )
        with self.assertRaises(live.AcceptanceError):
            live.validate_host_discovery_events(failed_turn, plan)

        events = [json.loads(line) for line in raw.splitlines()]
        for event in events:
            item = event.get("item", {})
            if item.get("type") == "mcp_tool_call":
                item.pop("id")
        missing_ids = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in events
        )
        with self.assertRaises(live.AcceptanceError):
            live.validate_host_discovery_events(missing_ids, plan)

        events = [json.loads(line) for line in raw.splitlines()]
        for event in events:
            item = event.get("item", {})
            if event.get("type") == "item.completed" and item.get("tool") == "jackal_claim":
                item["result"]["structured_content"]["bundle_digest_sha256"] = "f" * 64
                item["result"]["content"][0]["text"] = json.dumps(
                    item["result"]["structured_content"],
                    sort_keys=True,
                    separators=(",", ":"),
                )
        wrong_digest = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in events
        )
        with self.assertRaises(live.AcceptanceError):
            live.validate_host_discovery_events(wrong_digest, plan)

    def test_host_mcp_completion_requires_matching_text_and_structured_content(self):
        plan = self.plan()
        baseline = [json.loads(line) for line in self.event_bytes(plan).splitlines()]
        completion_index = next(
            index
            for index, event in enumerate(baseline)
            if event.get("type") == "item.completed"
            and event.get("item", {}).get("type") == "mcp_tool_call"
        )

        mutations = []
        missing = copy.deepcopy(baseline)
        missing[completion_index]["item"]["result"].pop("content")
        mutations.append(missing)
        malformed = copy.deepcopy(baseline)
        malformed[completion_index]["item"]["result"]["content"] = []
        mutations.append(malformed)
        divergent = copy.deepcopy(baseline)
        divergent[completion_index]["item"]["result"]["content"][0]["text"] = "{}"
        mutations.append(divergent)
        unknown = copy.deepcopy(baseline)
        unknown[completion_index]["item"]["result"]["unexpected"] = True
        mutations.append(unknown)

        for events in mutations:
            with self.subTest(result=events[completion_index]["item"]["result"]):
                raw = b"".join(
                    json.dumps(event, separators=(",", ":")).encode() + b"\n"
                    for event in events
                )
                with self.assertRaisesRegex(
                    live.AcceptanceError, "content|result shape"
                ):
                    live.validate_host_discovery_events(raw, plan)

    def test_host_claim_and_verification_require_complete_backend_semantics(self):
        plan = self.plan()
        baseline = [json.loads(line) for line in self.event_bytes(plan).splitlines()]
        claim_index = next(
            index
            for index, event in enumerate(baseline)
            if event.get("type") == "item.completed"
            and event.get("item", {}).get("tool") == "jackal_claim"
        )
        verify_index = next(
            index
            for index, event in enumerate(baseline)
            if event.get("type") == "item.completed"
            and event.get("item", {}).get("tool") == "jackal_verify_bundle"
        )

        def synchronize(events, event_index):
            result = events[event_index]["item"]["result"]
            result["content"][0]["text"] = json.dumps(
                result["structured_content"],
                sort_keys=True,
                separators=(",", ":"),
            )

        mutations = []
        missing_claim_field = copy.deepcopy(baseline)
        missing_claim_field[claim_index]["item"]["result"]["structured_content"].pop(
            "rendering"
        )
        synchronize(missing_claim_field, claim_index)
        mutations.append(missing_claim_field)
        wrong_claim_root = copy.deepcopy(baseline)
        wrong_claim_root[claim_index]["item"]["result"]["structured_content"][
            "root"
        ] = "unbound-root"
        synchronize(wrong_claim_root, claim_index)
        mutations.append(wrong_claim_root)
        missing_verified_marker = copy.deepcopy(baseline)
        missing_verified_marker[verify_index]["item"]["result"][
            "structured_content"
        ]["report"].remove("claim-verify=verified")
        synchronize(missing_verified_marker, verify_index)
        mutations.append(missing_verified_marker)
        wrong_bundle_digest = copy.deepcopy(baseline)
        report = wrong_bundle_digest[verify_index]["item"]["result"][
            "structured_content"
        ]["report"]
        report[report.index(next(line for line in report if line.startswith("bundle.digest=")))] = (
            "bundle.digest=" + "f" * 64
        )
        synchronize(wrong_bundle_digest, verify_index)
        mutations.append(wrong_bundle_digest)
        misleading_freshness = copy.deepcopy(baseline)
        report = misleading_freshness[verify_index]["item"]["result"][
            "structured_content"
        ]["report"]
        report[report.index(next(line for line in report if line.startswith("freshness:")))] = (
            "fabricated failure text nonce=bound"
        )
        synchronize(misleading_freshness, verify_index)
        mutations.append(misleading_freshness)
        extra_verify_field = copy.deepcopy(baseline)
        extra_verify_field[verify_index]["item"]["result"]["structured_content"][
            "unexpected"
        ] = True
        synchronize(extra_verify_field, verify_index)
        mutations.append(extra_verify_field)

        for events in mutations:
            with self.subTest(events=events):
                raw = b"".join(
                    json.dumps(event, separators=(",", ":")).encode() + b"\n"
                    for event in events
                )
                with self.assertRaisesRegex(
                    live.AcceptanceError,
                    "claim|bundle|verifier|verification|freshness|report",
                ):
                    live.validate_host_discovery_events(raw, plan)

    def test_host_event_stream_requires_global_start_complete_order(self):
        plan = self.plan()
        events = [json.loads(line) for line in self.event_bytes(plan).splitlines()]
        reordered = [
            events[0], events[1], events[3], events[2], events[5], events[4],
            events[6], events[7],
        ]
        raw = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in reordered
        )

        with self.assertRaisesRegex(live.AcceptanceError, "lifecycle order"):
            live.validate_host_discovery_events(raw, plan)

    def test_host_event_stream_requires_complete_ordered_outer_lifecycle(self):
        plan = self.plan()
        events = [json.loads(line) for line in self.event_bytes(plan).splitlines()]

        missing_turn_start = events[:1] + events[2:]
        raw = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in missing_turn_start
        )
        with self.assertRaisesRegex(live.AcceptanceError, "outer lifecycle"):
            live.validate_host_discovery_events(raw, plan)

        reordered = [events[7], *events[2:7], events[1], events[0]]
        raw = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in reordered
        )
        with self.assertRaisesRegex(live.AcceptanceError, "outer lifecycle"):
            live.validate_host_discovery_events(raw, plan)

        prefixed = (
            b'{"type":"item.completed","item":{"id":"early",'
            b'"type":"reasoning","text":"premature"}}\n'
            + self.event_bytes(plan)
        )
        with self.assertRaisesRegex(live.AcceptanceError, "outer lifecycle"):
            live.validate_host_discovery_events(prefixed, plan)

    def test_host_event_stream_rejects_shell_file_web_and_wrong_server_events(self):
        plan = self.plan()
        raw = self.event_bytes(plan)
        forbidden = (
            {"type": "item.started", "item": {"id": "x", "type": "command_execution"}},
            {"type": "item.updated", "item": {"id": "x", "type": "command_execution"}},
            {"type": "item.completed", "item": {"id": "x", "type": "file_change"}},
            {"type": "item.updated", "item": {"id": "x", "type": "web_search"}},
            {"type": "item.completed", "item": {"id": "x", "type": "web_search"}},
            {"type": "item.updated", "item": {"id": "x", "type": "collab_tool_call"}},
        )
        for event in forbidden:
            with self.subTest(event=event["item"]["type"]):
                injected = (
                    json.dumps(event, separators=(",", ":")).encode() + b"\n" + raw
                )
                with self.assertRaises(live.AcceptanceError):
                    live.validate_host_discovery_events(injected, plan)
        wrong_server = raw.replace(b'"server":"jackel"', b'"server":"other"', 1)
        with self.assertRaises(live.AcceptanceError):
            live.validate_host_discovery_events(wrong_server, plan)

        events = [json.loads(line) for line in raw.splitlines()]
        events.insert(-1, {
            "type": "item.updated",
            "item": {
                "id": "extra",
                "type": "mcp_tool_call",
                "server": "other",
                "tool": "unrelated_tool",
                "arguments": {},
                "status": "in_progress",
                "result": None,
                "error": None,
            },
        })
        unexpected_mcp_update = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in events
        )
        with self.assertRaisesRegex(live.AcceptanceError, "unexpected MCP"):
            live.validate_host_discovery_events(unexpected_mcp_update, plan)

        unknown_top_level = (
            b'{"type":"unknown.lifecycle","payload":{}}\n' + raw
        )
        with self.assertRaisesRegex(live.AcceptanceError, "event type"):
            live.validate_host_discovery_events(unknown_top_level, plan)

    def test_host_event_stream_binds_expected_mcp_updates_by_id_and_arguments(self):
        plan = self.plan()
        events = [json.loads(line) for line in self.event_bytes(plan).splitlines()]
        update = copy.deepcopy(events[2])
        update["type"] = "item.updated"
        events.insert(3, update)
        raw = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in events
        )
        live.validate_host_discovery_events(raw, plan)

        malformed = copy.deepcopy(events)
        malformed[3]["item"]["id"] = []
        raw = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in malformed
        )
        with self.assertRaisesRegex(live.AcceptanceError, "unexpected MCP update"):
            live.validate_host_discovery_events(raw, plan)

    def test_host_event_stream_requires_exact_item_states_update_window_and_usage(self):
        plan = self.plan()
        baseline = [json.loads(line) for line in self.event_bytes(plan).splitlines()]

        failed_start = copy.deepcopy(baseline)
        failed_start[2]["item"]["status"] = "failed"
        raw = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in failed_start
        )
        with self.assertRaisesRegex(live.AcceptanceError, "MCP item state"):
            live.validate_host_discovery_events(raw, plan)

        incomplete_turn = copy.deepcopy(baseline)
        incomplete_turn[-1]["usage"].pop("input_tokens")
        raw = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in incomplete_turn
        )
        with self.assertRaisesRegex(live.AcceptanceError, "turn usage"):
            live.validate_host_discovery_events(raw, plan)

        late_update = copy.deepcopy(baseline[2])
        late_update["type"] = "item.updated"
        after_completion = [*baseline[:-1], late_update, baseline[-1]]
        raw = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in after_completion
        )
        with self.assertRaisesRegex(live.AcceptanceError, "update order"):
            live.validate_host_discovery_events(raw, plan)

    def test_host_event_stream_accepts_known_extended_usage_only(self):
        plan = self.plan()
        events = [json.loads(line) for line in self.event_bytes(plan).splitlines()]
        events[-1]["usage"].update({
            "cache_write_input_tokens": 5,
            "reasoning_output_tokens": 7,
        })
        raw = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in events
        )
        live.validate_host_discovery_events(raw, plan)

        events[-1]["usage"]["unknown_tokens"] = 1
        raw = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in events
        )
        with self.assertRaisesRegex(live.AcceptanceError, "turn usage"):
            live.validate_host_discovery_events(raw, plan)

    def test_host_event_stream_correlates_passive_items_inside_turn(self):
        plan = self.plan()
        baseline = self.event_bytes(plan)
        early = [json.loads(line) for line in baseline.splitlines()]
        early.insert(1, {
            "type": "item.started",
            "item": {"id": "reasoning-id", "type": "reasoning"},
        })
        incomplete = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in early
        )
        with self.assertRaisesRegex(live.AcceptanceError, "passive|turn"):
            live.validate_host_discovery_events(incomplete, plan)

        events = [json.loads(line) for line in baseline.splitlines()]
        events.insert(-1, {
            "type": "item.started",
            "item": {"id": "reasoning-id", "type": "reasoning"},
        })
        raw = b"".join(
            json.dumps(event, separators=(",", ":")).encode() + b"\n"
            for event in events
        )
        with self.assertRaisesRegex(live.AcceptanceError, "passive"):
            live.validate_host_discovery_events(raw, plan)

    def test_host_event_stream_requires_canonical_event_and_item_shapes(self):
        plan = self.plan()
        baseline = [json.loads(line) for line in self.event_bytes(plan).splitlines()]
        mutations = []
        for event_index in (0, 1, 2, len(baseline) - 1):
            changed = copy.deepcopy(baseline)
            changed[event_index]["unexpected"] = True
            mutations.append(changed)
        missing_event_field = copy.deepcopy(baseline)
        missing_event_field[-1].pop("usage")
        mutations.append(missing_event_field)
        extra_mcp_field = copy.deepcopy(baseline)
        extra_mcp_field[2]["item"]["unexpected"] = True
        mutations.append(extra_mcp_field)
        missing_passive_text = copy.deepcopy(baseline)
        missing_passive_text[-2]["item"].pop("text")
        mutations.append(missing_passive_text)
        wrong_passive_text = copy.deepcopy(baseline)
        wrong_passive_text[-2]["item"]["text"] = {"not": "text"}
        mutations.append(wrong_passive_text)
        ghost_passive = copy.deepcopy(baseline)
        ghost_passive.insert(-1, {
            "type": "item.completed",
            "item": {"id": "ghost", "type": "reasoning"},
        })
        mutations.append(ghost_passive)

        for events in mutations:
            with self.subTest(events=events):
                raw = b"".join(
                    json.dumps(event, separators=(",", ":")).encode() + b"\n"
                    for event in events
                )
                with self.assertRaisesRegex(
                    live.AcceptanceError, "schema|shape|passive"
                ):
                    live.validate_host_discovery_events(raw, plan)

    def test_host_registry_binds_exact_enabled_server_to_verified_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory).resolve()
            (installed / ".mcp.json").write_bytes(
                (live.PLUGIN_ROOT / ".mcp.json").read_bytes()
            )
            raw = self.registry_bytes(installed)

            self.assertEqual(
                live.validate_host_mcp_registry(raw, installed), installed
            )
            document = json.loads(raw)
            document[0]["transport"]["cwd"] = str(installed.parent)
            with self.assertRaisesRegex(live.AcceptanceError, "verified cache"):
                live.validate_host_mcp_registry(
                    json.dumps(document).encode(), installed
                )
            document = json.loads(raw)
            document.append(copy.deepcopy(document[0]))
            with self.assertRaisesRegex(live.AcceptanceError, "exactly one"):
                live.validate_host_mcp_registry(
                    json.dumps(document).encode(), installed
                )

    def test_host_runner_checks_identity_before_and_after_and_records_raw_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            codex_home = root / "codex-home"
            codex_home.mkdir()
            codex_binary = root / "codex"
            codex_binary.write_bytes(b"fixture codex executable")
            codex_binary.chmod(0o755)
            evidence = root / "host-evidence.jsonl"
            installed = root / "installed"
            installed.mkdir()
            (installed / ".mcp.json").write_bytes(
                (live.PLUGIN_ROOT / ".mcp.json").read_bytes()
            )
            plan = live.build_host_discovery_plan(
                codex_binary=codex_binary,
                codex_home=codex_home,
                runtime_root=Path("/absolute/runtime"),
                nonce="host-proof-nonce-0123456789abcdef",
                emitted_at_unix="1786752000",
            )
            raw = self.event_bytes(plan)
            version_command = (str(codex_binary), "--version")
            registry_command = (str(codex_binary), "mcp", "list", "--json")
            registry = self.registry_bytes(installed)
            runner = mock.Mock(side_effect=(
                subprocess.CompletedProcess(
                    version_command, 0, b"codex-cli 0.146.0\n", b""
                ),
                subprocess.CompletedProcess(registry_command, 0, registry, b""),
                subprocess.CompletedProcess(plan.command, 0, raw, b""),
                subprocess.CompletedProcess(registry_command, 0, registry, b""),
                subprocess.CompletedProcess(
                    version_command, 0, b"codex-cli 0.146.0\n", b""
                ),
            ))
            with (
                mock.patch.object(live, "verify_wrapper", return_value="b" * 64),
                mock.patch.object(live, "verify_runtime") as verify_runtime,
                mock.patch.object(
                    live, "locate_cache_copy", side_effect=(installed, installed)
                ) as locate,
            ):
                report = live.run_host_discovery_acceptance(
                    codex_binary=codex_binary,
                    codex_home=codex_home,
                    runtime_root=Path("/absolute/runtime"),
                    evidence_path=evidence,
                    runner=runner,
                    nonce_factory=lambda: "host-proof-nonce-0123456789abcdef",
                    clock=lambda: 1786752000,
                )

            self.assertEqual(evidence.read_bytes(), raw)
            self.assertEqual(evidence.stat().st_mode & 0o777, 0o600)
            self.assertEqual(locate.call_count, 2)
            self.assertEqual(verify_runtime.call_count, 2)
            self.assertEqual(runner.call_count, 5)
            self.assertEqual(
                [call.args[0] for call in runner.call_args_list],
                [
                    version_command,
                    registry_command,
                    plan.command,
                    registry_command,
                    version_command,
                ],
            )
            host_environment = runner.call_args_list[2].kwargs["environment"]
            self.assertEqual(host_environment["CODEX_HOME"], str(codex_home))
            self.assertEqual(host_environment["JACKAL_HOME"], "/absolute/runtime")
            for forbidden in ("PYTHONPATH", "PYTHONHOME", "DYLD_INSERT_LIBRARIES"):
                self.assertNotIn(forbidden, host_environment)
            self.assertEqual(report["status"], "accepted")
            self.assertEqual(report["active_mcp_cwd"], str(installed.resolve()))
            self.assertEqual(report["codex_binary_invocation_path"], str(codex_binary))
            self.assertEqual(report["codex_binary_resolved_path"], str(codex_binary))
            self.assertEqual(report["codex_binary_version"], "codex-cli 0.146.0")
            self.assertEqual(
                report["codex_binary_sha256"],
                hashlib.sha256(codex_binary.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                report["codex_binary_trust"], "caller-supplied-external-anchor"
            )
            with self.assertRaisesRegex(live.AcceptanceError, "evidence path"):
                live.run_host_discovery_acceptance(
                    codex_binary=Path("/absolute/codex"),
                    codex_home=codex_home,
                    runtime_root=Path("/absolute/runtime"),
                    evidence_path=evidence,
                    runner=runner,
                    nonce_factory=lambda: "host-proof-nonce-0123456789abcdef",
                    clock=lambda: 1786752000,
                )

    def test_host_runner_refuses_binary_replacement_during_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            codex_home = root / "codex-home"
            codex_home.mkdir()
            codex_binary = root / "codex"
            codex_binary.write_bytes(b"fixture codex executable v1")
            codex_binary.chmod(0o755)
            evidence = root / "host-evidence.jsonl"
            installed = root / "installed"
            installed.mkdir()
            (installed / ".mcp.json").write_bytes(
                (live.PLUGIN_ROOT / ".mcp.json").read_bytes()
            )
            plan = live.build_host_discovery_plan(
                codex_binary=codex_binary,
                codex_home=codex_home,
                runtime_root=Path("/absolute/runtime"),
                nonce="host-proof-nonce-0123456789abcdef",
                emitted_at_unix="1786752000",
            )
            raw = self.event_bytes(plan)
            registry = self.registry_bytes(installed)
            calls = 0

            def runner(command, **unused):
                nonlocal calls
                calls += 1
                if calls in (1, 5):
                    return subprocess.CompletedProcess(
                        command, 0, b"codex-cli 0.146.0\n", b""
                    )
                if calls in (2, 4):
                    return subprocess.CompletedProcess(command, 0, registry, b"")
                self.assertEqual(calls, 3)
                codex_binary.write_bytes(b"fixture codex executable v2")
                codex_binary.chmod(0o755)
                return subprocess.CompletedProcess(command, 0, raw, b"")

            with (
                mock.patch.object(live, "verify_wrapper", return_value="b" * 64),
                mock.patch.object(live, "verify_runtime"),
                mock.patch.object(
                    live, "locate_cache_copy", side_effect=(installed, installed)
                ),
                self.assertRaisesRegex(live.AcceptanceError, "binary identity changed"),
            ):
                live.run_host_discovery_acceptance(
                    codex_binary=codex_binary,
                    codex_home=codex_home,
                    runtime_root=Path("/absolute/runtime"),
                    evidence_path=evidence,
                    runner=runner,
                    nonce_factory=lambda: "host-proof-nonce-0123456789abcdef",
                    clock=lambda: 1786752000,
                )

            self.assertEqual(calls, 5)
            self.assertEqual(evidence.read_bytes(), raw)

    def test_host_live_cli_dispatches_only_with_absolute_explicit_paths(self):
        arguments = [
            "--host-live",
            "--codex-home", "/absolute/codex-home",
            "--codex-binary", "/absolute/codex",
            "--runtime-root", "/absolute/runtime",
            "--host-evidence", "/absolute/host-evidence.jsonl",
        ]
        with (
            mock.patch.object(
                live,
                "run_host_discovery_acceptance",
                return_value={"status": "accepted"},
            ) as runner,
            mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as stdout,
        ):
            self.assertEqual(live.main(arguments), 0)
        runner.assert_called_once_with(
            codex_binary=Path("/absolute/codex"),
            codex_home=Path("/absolute/codex-home"),
            runtime_root=Path("/absolute/runtime"),
            evidence_path=Path("/absolute/host-evidence.jsonl"),
        )
        self.assertEqual(json.loads(stdout.getvalue()), {"status": "accepted"})

    def test_host_process_cleanup_bounds_the_final_wait(self):
        process = mock.Mock(pid=43210)
        process.wait.side_effect = subprocess.TimeoutExpired(["codex"], 0.5)
        with (
            mock.patch.object(
                live.provisioner, "_cleanup_completed_process_group"
            ) as cleanup_group,
            self.assertRaisesRegex(live.AcceptanceError, "did not exit"),
        ):
            live._terminate_host_process(process)

        cleanup_group.assert_called_once_with(
            43210, live.provisioner._cleanup_process_group, live.os.killpg
        )

    def test_host_cleanup_signals_group_when_quiescence_observer_fails(self):
        process = mock.Mock(pid=43214)
        process.wait.return_value = 0
        with (
            mock.patch.object(
                live.provisioner,
                "_exited_group_has_only_zombie_members",
                side_effect=live.provisioner.ProvisionError("observer unavailable"),
            ),
            mock.patch.object(
                live.os,
                "killpg",
                side_effect=(None, ProcessLookupError()),
            ) as kill_group,
        ):
            self.assertEqual(live._terminate_host_process(process), 0)

        self.assertEqual(
            kill_group.call_args_list,
            [mock.call(43214, signal.SIGTERM), mock.call(43214, 0)],
        )
        process.wait.assert_called_once_with(timeout=0.5)

    def test_host_runner_cleans_up_when_selector_allocation_fails(self):
        process = mock.Mock(pid=43211)
        process.stdout = io.BytesIO()
        process.stderr = io.BytesIO()
        with (
            mock.patch.object(live.subprocess, "Popen", return_value=process),
            mock.patch.object(
                live.selectors, "DefaultSelector", side_effect=OSError("no fds")
            ),
            mock.patch.object(live, "_terminate_host_process") as terminate,
            self.assertRaisesRegex(live.AcceptanceError, "failed within bounds"),
        ):
            live._run_bounded_host_command(
                ("/absolute/codex", "--version"),
                cwd=live.REPOSITORY_ROOT,
                environment={},
            )

        terminate.assert_called_once_with(process)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)

    def test_host_runner_normalizes_final_wait_timeout_after_cleanup(self):
        process = mock.Mock(pid=43212)
        process.stdout = io.BytesIO()
        process.stderr = io.BytesIO()
        process.wait.side_effect = subprocess.TimeoutExpired(["codex"], 0.1)
        selector = mock.Mock()
        selector.get_map.return_value = {}
        with (
            mock.patch.object(live.subprocess, "Popen", return_value=process),
            mock.patch.object(live.selectors, "DefaultSelector", return_value=selector),
            mock.patch.object(
                live.provisioner,
                "_leader_exited_without_reaping",
                return_value=True,
            ),
            mock.patch.object(
                live.provisioner, "_cleanup_completed_process_group"
            ) as cleanup_group,
            self.assertRaisesRegex(live.AcceptanceError, "did not exit"),
        ):
            live._run_bounded_host_command(
                ("/absolute/codex", "--version"),
                cwd=live.REPOSITORY_ROOT,
                environment={},
            )

        cleanup_group.assert_called_once()
        selector.close.assert_called_once_with()
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)

    def test_host_runner_retains_leader_anchor_and_cleans_group_before_reap(self):
        process = mock.Mock(pid=43213)
        process.stdout = io.BytesIO()
        process.stderr = io.BytesIO()
        process.wait.return_value = 0
        selector = mock.Mock()
        selector.get_map.return_value = {}
        events = []

        def observe(unused_pid, unused_waitid):
            events.append("leader-observed-without-reap")
            self.assertEqual(process.wait.call_count, 0)
            return True

        def cleanup(process_group, cleanup_group, kill_group):
            events.append("whole-group-cleanup")
            self.assertEqual(process_group, process.pid)
            self.assertIs(cleanup_group, live.provisioner._cleanup_process_group)
            self.assertIs(kill_group, live.os.killpg)
            self.assertEqual(process.wait.call_count, 0)

        with (
            mock.patch.object(live.subprocess, "Popen", return_value=process),
            mock.patch.object(live.selectors, "DefaultSelector", return_value=selector),
            mock.patch.object(
                live.provisioner,
                "_leader_exited_without_reaping",
                side_effect=observe,
            ) as observe_anchor,
            mock.patch.object(
                live.provisioner,
                "_cleanup_completed_process_group",
                side_effect=cleanup,
            ) as cleanup_group,
        ):
            completed = live._run_bounded_host_command(
                ("/absolute/codex", "--version"),
                cwd=live.REPOSITORY_ROOT,
                environment={},
            )

        self.assertEqual(completed.returncode, 0)
        observe_anchor.assert_called()
        cleanup_group.assert_called_once()
        self.assertEqual(
            events, ["leader-observed-without-reap", "whole-group-cleanup"]
        )
        process.wait.assert_called_once()

    def test_host_cleanup_kills_resistant_descendant_after_leader_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pid_path = root / "child.pid"
            ready_path = root / "child.ready"
            child_source = (
                "import signal,sys,time\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "open(sys.argv[1], 'w').write('ready')\n"
                "time.sleep(30)\n"
            )
            leader_source = (
                "import os,subprocess,sys,time\n"
                "child=subprocess.Popen([sys.executable,'-I','-S','-B','-c',"
                "sys.argv[1],sys.argv[3]])\n"
                "while not os.path.exists(sys.argv[3]): time.sleep(0.01)\n"
                "open(sys.argv[2], 'w').write(str(child.pid))\n"
                "time.sleep(30)\n"
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    "-c",
                    leader_source,
                    child_source,
                    str(pid_path),
                    str(ready_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            child_pid = None
            try:
                deadline = time.monotonic() + 2.0
                published_pid = ""
                while time.monotonic() < deadline:
                    try:
                        published_pid = pid_path.read_text().strip()
                    except FileNotFoundError:
                        published_pid = ""
                    if published_pid.isdigit():
                        break
                    time.sleep(0.01)
                self.assertTrue(
                    published_pid.isdigit(),
                    "resistant descendant did not publish a complete PID",
                )
                child_pid = int(published_pid)

                live._terminate_host_process(process)

                deadline = time.monotonic() + 2.0
                state = ""
                while time.monotonic() < deadline:
                    state = subprocess.run(
                        ["/bin/ps", "-o", "state=", "-p", str(child_pid)],
                        capture_output=True,
                        text=True,
                        check=False,
                    ).stdout.strip()
                    if not state or state.startswith("Z"):
                        break
                    time.sleep(0.01)
                self.assertTrue(
                    not state or state.startswith("Z"),
                    f"host descendant survived cleanup: {state}",
                )
            finally:
                if process.returncode is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=1)
                if child_pid is not None:
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass


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
    def test_live_mcp_and_direct_comparator_share_one_sanitized_environment(self):
        runtime = Path("/absolute/pinned-runtime")
        installed = Path("/absolute/installed-plugin")
        environment = {
            "PATH": "/fixed/python:/usr/bin:/bin:/usr/sbin:/sbin",
            "JACKAL_HOME": str(runtime),
        }
        client = mock.Mock()
        client_context = mock.Mock()
        client_context.__enter__ = mock.Mock(return_value=client)
        client_context.__exit__ = mock.Mock(return_value=False)
        direct = mock.Mock(return_value={"status": "exact"})
        temporary = mock.Mock()
        temporary.__enter__ = mock.Mock(
            return_value="/private/tmp/jackel-codex-live-fixture"
        )
        temporary.__exit__ = mock.Mock(return_value=False)

        def acceptance(*, client, runtime_document, direct_call):
            self.assertEqual(runtime_document, {"tools": []})
            direct_call("jackal_exact", {"expression": "1+1"})
            return {"sequence": "accepted"}

        with (
            mock.patch.object(live, "verify_wrapper", return_value="a" * 64),
            mock.patch.object(live, "verify_runtime"),
            mock.patch.object(live, "load_runtime_document", return_value={"tools": []}),
            mock.patch.object(
                live.tempfile, "TemporaryDirectory", return_value=temporary
            ) as temporary_directory,
            mock.patch.object(live, "build_codex_install_plan", return_value=mock.Mock()),
            mock.patch.object(live, "execute_codex_install"),
            mock.patch.object(live, "locate_cache_copy", return_value=installed),
            mock.patch.object(
                live, "runtime_acceptance_environment", return_value=environment
            ) as sanitizer,
            mock.patch.object(
                live, "installed_mcp_client", return_value=client_context
            ) as mcp_client,
            mock.patch.object(live, "direct_backend_call", direct),
            mock.patch.object(live, "run_acceptance", side_effect=acceptance),
        ):
            report = live._live(runtime, Path("/absolute/codex"))

        sanitizer.assert_called_once()
        temporary_directory.assert_called_once_with(
            prefix="jackel-codex-live-", dir=Path("/private/tmp")
        )
        self.assertEqual(sanitizer.call_args.args[0], runtime)
        mcp_client.assert_called_once_with(installed, environment)
        direct.assert_called_once_with(
            runtime,
            "jackal_exact",
            {"expression": "1+1"},
            environment=environment,
        )
        self.assertEqual(report["sequence"], "accepted")

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
        # Exact against the catalog actually fed in — this test feeds the repo
        # `plugin/hermes/tools.json`, so retyping its size here would go stale
        # on every surface addition while checking nothing extra.
        self.assertEqual(report["discovered_tool_count"],
                         len(runtime_document["tools"]))
        self.assertGreaterEqual(report["discovered_tool_count"], live.MIN_TOOL_COUNT)
        self.assertEqual(report["gates"], {
            "exact": "exact", "formal": "formal-bounded",
            "unsupported_formal": "producer-refused",
            "claim_bundle": "verified", "formal_receipt": "verified",
        })


if __name__ == "__main__":
    unittest.main()
