import asyncio
import copy
import errno
import hashlib
import importlib.util
import io
import json
import os
import py_compile
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from plugins.jackel.mcp import server as adapter
from plugins.jackel.mcp import advanced
from plugins.jackel.mcp import measurement
from plugins.jackel.mcp import stem
from plugins.jackel.mcp import numbertheory
from plugins.jackel.mcp import engineering
from plugins.jackel.scripts import provision_runtime as real_provisioner


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_TOOLS = REPO_ROOT / "plugin/hermes/tools.json"
TEST_RUNTIME_ENVIRONMENT = real_provisioner.runtime_subprocess_environment({})

# The REPO surface size, read from the file under test.  It is deliberately not
# `adapter.EXPECTED_TOOL_COUNT`: that constant locks the SEALED RELEASE catalog
# the provisioner downloads (pinned by `provision_runtime.SHA256SUMS_SHA256`),
# and the repo surface moves ahead of a release between seals.  Conflating the
# two is what makes a repo-side surface addition look like an adapter failure.
RUNTIME_TOOL_COUNT = len(
    json.loads(RUNTIME_TOOLS.read_text(encoding="utf-8"))["tools"]
)


class MCPAdapterSchemaTests(unittest.TestCase):
    def setUp(self):
        self.runtime_document = json.loads(RUNTIME_TOOLS.read_text(encoding="utf-8"))

    def test_all_runtime_tools_become_draft_07_object_schemas(self):
        definitions = adapter.build_tool_definitions(
            self.runtime_document, expected_count=RUNTIME_TOOL_COUNT)
        records = self.runtime_document["tools"]

        self.assertEqual(len(definitions), RUNTIME_TOOL_COUNT)
        self.assertEqual(
            [definition["name"] for definition in definitions],
            [record["name"] for record in records],
        )
        self.assertEqual(
            len({definition["name"] for definition in definitions}),
            RUNTIME_TOOL_COUNT,
        )

        for record, definition in zip(records, definitions, strict=True):
            with self.subTest(tool=record["name"]):
                self.assertEqual(definition["name"], record["name"])
                self.assertEqual(definition["description"], record["description"])
                schema = definition["inputSchema"]
                self.assertEqual(schema["$schema"], "http://json-schema.org/draft-07/schema#")
                self.assertEqual(schema["type"], "object")
                self.assertIs(schema["additionalProperties"], False)
                self.assertEqual(
                    schema["required"],
                    [
                        name
                        for name, argument in record["arguments"].items()
                        if argument["required"]
                    ],
                )
                self.assertEqual(list(schema["properties"]), list(record["arguments"]))
                for name, argument in record["arguments"].items():
                    self.assertEqual(
                        schema["properties"][name],
                        {"type": argument["type"], "description": argument["help"]},
                    )

    def test_catalog_rejects_duplicate_names_and_unsupported_argument_types(self):
        duplicate = copy.deepcopy(self.runtime_document)
        duplicate["tools"][1]["name"] = duplicate["tools"][0]["name"]
        with self.assertRaises(adapter.CatalogError):
            adapter.build_tool_definitions(duplicate, expected_count=RUNTIME_TOOL_COUNT)

        unsupported = copy.deepcopy(self.runtime_document)
        unsupported["tools"][0]["arguments"]["expression"]["type"] = "number"
        with self.assertRaises(adapter.CatalogError):
            adapter.build_tool_definitions(unsupported, expected_count=RUNTIME_TOOL_COUNT)

    def test_catalog_requires_exact_tool_count(self):
        """Non-vacuity for the derived count: an off-by-one must still refuse."""
        for wrong in (RUNTIME_TOOL_COUNT - 1, RUNTIME_TOOL_COUNT + 1):
            with self.subTest(expected_count=wrong):
                with self.assertRaises(adapter.CatalogError):
                    adapter.build_tool_definitions(
                        self.runtime_document, expected_count=wrong)

    def test_backend_object_is_preserved_and_has_stable_compact_text(self):
        backend = {
            "status": "formal-bounded",
            "receipt": {"z": [3, {"b": True, "a": None}], "a": "μ"},
            "enclosure": ["1/3", "2/3"],
        }
        before = copy.deepcopy(backend)
        result = adapter.backend_result(backend)

        self.assertEqual(result["structuredContent"], backend)
        self.assertEqual(result["structuredContent"], before)
        self.assertIsNot(result["structuredContent"], backend)
        self.assertNotIn("isError", result)
        self.assertEqual(
            result["content"],
            [{
                "type": "text",
                "text": json.dumps(
                    backend, ensure_ascii=False, allow_nan=False,
                    sort_keys=True, separators=(",", ":"),
                ),
            }],
        )

    def test_refused_and_indeterminate_are_successful_results_without_promotion(self):
        for status in ("refused", "indeterminate"):
            with self.subTest(status=status):
                backend = {"status": status, "reason": "bounded-test"}
                result = adapter.backend_result(backend)
                self.assertEqual(result["structuredContent"], backend)
                self.assertEqual(
                    json.loads(result["content"][0]["text"]),
                    backend,
                )
                self.assertNotIn("isError", result)
                self.assertEqual(result["structuredContent"]["status"], status)

    def test_plugin_root_comes_from_server_location_for_source_and_cache(self):
        for base in ("repo/plugins/jackel", "cache/jackel/0.1.0"):
            with self.subTest(base=base), tempfile.TemporaryDirectory() as directory:
                server_path = Path(directory) / base / "mcp/server.py"
                server_path.parent.mkdir(parents=True)
                server_path.write_text("# fixture\n", encoding="utf-8")
                self.assertEqual(
                    adapter.plugin_root_from_server(server_path),
                    server_path.parent.parent.resolve(),
                )

    def test_module_loader_executes_source_bytes_not_a_valid_stale_pyc(self):
        with tempfile.TemporaryDirectory() as directory:
            module_path = Path(directory) / "wrapper.py"
            fixed_timestamp = 1_700_000_000
            module_path.write_text("RESULT = 'cached'\n", encoding="utf-8")
            os.utime(module_path, (fixed_timestamp, fixed_timestamp))
            cache_path = Path(importlib.util.cache_from_source(str(module_path)))
            cache_path.parent.mkdir()
            py_compile.compile(
                str(module_path),
                cfile=str(cache_path),
                doraise=True,
                invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP,
            )
            module_path.write_text("RESULT = 'source'\n", encoding="utf-8")
            os.utime(module_path, (fixed_timestamp, fixed_timestamp))
            module_name = "jackal_stale_pyc_fixture"
            self.addCleanup(sys.modules.pop, module_name, None)

            loaded = adapter._load_module(module_path, module_name)

            self.assertEqual(loaded.RESULT, "source")

    def test_module_loader_never_creates_a_bytecode_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            module_path = Path(directory) / "wrapper.py"
            module_path.write_text("RESULT = 'source'\n", encoding="utf-8")
            module_name = "jackal_no_pyc_fixture"
            self.addCleanup(sys.modules.pop, module_name, None)

            with mock.patch.object(sys, "dont_write_bytecode", False):
                loaded = adapter._load_module(module_path, module_name)

            self.assertEqual(loaded.RESULT, "source")
            self.assertFalse((module_path.parent / "__pycache__").exists())

    def test_verified_wrapper_modules_execute_only_the_digest_checked_bytes(self):
        for index, relative in enumerate(
            ("scripts/verify_plugin.py", "scripts/provision_runtime.py")
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                module_path = root / relative
                module_path.parent.mkdir(parents=True)
                marker = root / "replacement-executed"
                original = b"RESULT = 'verified-original'\n"
                replacement = (
                    "from pathlib import Path\n"
                    f"Path({str(marker)!r}).write_text('bad')\n"
                    "RESULT = 'replacement'\n"
                ).encode("utf-8")
                module_path.write_bytes(original)
                records = {relative: hashlib.sha256(original).hexdigest()}
                real_execute = adapter._execute_module_bytes

                def replace_after_digest(source, path, module_name):
                    module_path.unlink()
                    module_path.write_bytes(replacement)
                    return real_execute(source, path, module_name)

                module_name = f"jackal_verified_bytes_fixture_{index}"
                self.addCleanup(sys.modules.pop, module_name, None)
                with mock.patch.object(
                    adapter, "_execute_module_bytes", side_effect=replace_after_digest
                ):
                    loaded = adapter._load_verified_module(
                        root, relative, module_name, records
                    )

                self.assertEqual(loaded.RESULT, "verified-original")
                self.assertFalse(marker.exists())
                self.assertFalse((module_path.parent / "__pycache__").exists())

    def test_verified_wrapper_module_digest_mismatch_refuses_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module_path = root / "scripts/verify_plugin.py"
            module_path.parent.mkdir(parents=True)
            marker = root / "executed"
            module_path.write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n",
                encoding="utf-8",
            )
            with self.assertRaises(adapter.StartupError):
                adapter._load_verified_module(
                    root, "scripts/verify_plugin.py", "jackal_digest_mismatch",
                    {"scripts/verify_plugin.py": "0" * 64},
                )
            self.assertFalse(marker.exists())


class MCPAdapterProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name) / "runtime"
        hermes = self.runtime / "plugin/hermes"
        hermes.mkdir(parents=True)
        self.pid_files = []
        self.launcher = hermes / "jackal_hermes"
        self.launcher.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import json
                import os
                import signal
                import subprocess
                import sys
                import time

                stdio_mode = len(sys.argv) == 2 and sys.argv[1] == "stdio"
                request_id = None
                if stdio_mode:
                    raw = sys.stdin.buffer.readline()
                    trailing = sys.stdin.buffer.read()
                    if not raw or trailing:
                        raise SystemExit(64)
                    request = json.loads(raw)
                    request_id = request.get("id")
                    name = request.get("method")
                    arguments = request.get("params")
                elif len(sys.argv) == 4 and sys.argv[1] == "call":
                    name = sys.argv[2]
                    arguments = json.loads(sys.argv[3])
                else:
                    raise SystemExit(64)
                allowed = {{"payload", "mode", "pid_file", "release_file"}}
                if (
                    not isinstance(arguments, dict)
                    or
                    "payload" not in arguments
                    or not isinstance(arguments.get("payload"), dict)
                    or any(key not in allowed for key in arguments)
                ):
                    refusal = {{
                        "status": "refused",
                        "reason": "plugin-args-schema",
                        "arguments": arguments,
                    }}
                    if stdio_mode:
                        refusal = {{
                            "jsonrpc": "2.0", "id": request_id, "result": refusal,
                        }}
                        print(json.dumps(refusal, sort_keys=True), flush=True)
                        raise SystemExit(0)
                    print(json.dumps(refusal, sort_keys=True), flush=True)
                    raise SystemExit(1)
                mode = arguments.get("mode", "echo")
                payload = arguments.get("payload", {{}})

                if mode == "stderr":
                    print("SENSITIVE-BACKEND-STDERR", file=sys.stderr, flush=True)
                elif mode == "invalid":
                    print("{{not-json", flush=True)
                    raise SystemExit(0)
                elif mode == "invalid-rc1":
                    print("{{not-json", flush=True)
                    raise SystemExit(1)
                elif mode == "multiple":
                    print("{{}}")
                    print("{{}}", flush=True)
                    raise SystemExit(0)
                elif mode == "duplicate":
                    print('{{"status":"checked","status":"formal-bounded"}}', flush=True)
                    raise SystemExit(0)
                elif mode == "nan":
                    print('{{"status":"checked","value":NaN}}', flush=True)
                    raise SystemExit(0)
                elif mode in ("tree", "hang"):
                    pid_file = arguments["pid_file"]
                    child_source = (
                        "import os,subprocess,sys,time;"
                        "g=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
                        "open(sys.argv[1],'a').write(str(os.getpid())+'\\\\n'+str(g.pid)+'\\\\n');"
                        "time.sleep(60)"
                    )
                    child = subprocess.Popen([sys.executable, "-c", child_source, pid_file])
                    with open(pid_file, "a", encoding="utf-8") as handle:
                        handle.write(str(os.getpid()) + "\\n" + str(child.pid) + "\\n")
                        handle.flush()
                        os.fsync(handle.fileno())
                    time.sleep(60)
                elif mode in ("resistant-tree", "resistant-output"):
                    pid_file = arguments["pid_file"]
                    grandchild_source = (
                        "import os,signal,sys,time;"
                        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                        "open(sys.argv[1],'a').write(str(os.getpid())+'\\\\n');"
                        "time.sleep(60)"
                    )
                    child_source = (
                        "import os,signal,subprocess,sys,time;"
                        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                        "g=subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[1]],"
                        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
                        "open(sys.argv[1],'a').write(str(os.getpid())+'\\\\n');"
                        "time.sleep(60)"
                    )
                    child = subprocess.Popen(
                        [sys.executable, "-c", child_source, pid_file, grandchild_source],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )

                    def exit_on_term(unused_signum, unused_frame):
                        raise SystemExit(0)

                    signal.signal(signal.SIGTERM, exit_on_term)
                    with open(pid_file, "a", encoding="utf-8") as handle:
                        handle.write(str(os.getpid()) + "\\n" + str(child.pid) + "\\n")
                        handle.flush()
                        os.fsync(handle.fileno())
                    if mode == "resistant-output":
                        deadline = time.monotonic() + 2
                        while time.monotonic() < deadline:
                            with open(pid_file, encoding="utf-8") as handle:
                                if len(set(handle.read().splitlines())) >= 3:
                                    break
                            time.sleep(0.005)
                        print(json.dumps({{"status": "checked", "blob": "x" * 8192}}), flush=True)
                    time.sleep(60)
                elif mode in ("orphan-hold-exit", "orphan-hold-crash", "orphan-output-exit"):
                    pid_file = arguments["pid_file"]
                    child_source = (
                        "import os,signal,sys,time;"
                        "mode=sys.argv[1];parent=int(sys.argv[2]);"
                        "time.sleep(0.1);"
                        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                        "signal.pthread_sigmask(signal.SIG_UNBLOCK,{{signal.SIGTERM}});"
                        "exec(\\\"while mode == 'output' and os.getppid() == parent:\\\\n time.sleep(0.005)\\\");"
                        "time.sleep(0.15) if mode == 'output' else None;"
                        "os.write(1,b'x'*8192) if mode == 'output' else None;"
                        "time.sleep(60)"
                    )
                    child_modes = (
                        ("output", "hold")
                        if mode == "orphan-output-exit"
                        else ("hold", "hold")
                    )
                    signal.pthread_sigmask(signal.SIG_BLOCK, {{signal.SIGTERM}})
                    try:
                        children = [
                            subprocess.Popen(
                                [sys.executable, "-c", child_source, child_mode, str(os.getpid())]
                            )
                            for child_mode in child_modes
                        ]
                    finally:
                        signal.pthread_sigmask(signal.SIG_UNBLOCK, {{signal.SIGTERM}})
                    with open(pid_file, "a", encoding="utf-8") as handle:
                        handle.write(
                            str(os.getpid())
                            + "\\n"
                            + "\\n".join(str(child.pid) for child in children)
                            + "\\n"
                        )
                        handle.flush()
                        os.fsync(handle.fileno())
                    release_file = arguments.get("release_file")
                    if release_file is not None:
                        release_deadline = time.monotonic() + 5
                        while not os.path.isfile(release_file):
                            if time.monotonic() >= release_deadline:
                                raise SystemExit(70)
                            time.sleep(0.005)
                    if mode == "orphan-hold-crash":
                        os.kill(os.getpid(), signal.SIGKILL)
                    raise SystemExit(0)
                elif mode == "slow":
                    time.sleep(0.35)
                elif mode == "oversize-stdout":
                    print(json.dumps({{"status": "checked", "blob": "x" * 8192}}), flush=True)
                    raise SystemExit(0)

                if mode == "accept-large":
                    result = {{"status": "checked", "accepted": True}}
                elif mode == "refused":
                    result = {{"status": "refused", "reason": "fixture-refusal", "input": payload}}
                elif mode == "indeterminate":
                    result = {{"status": "indeterminate", "reason": "fixture-indeterminate", "input": payload}}
                else:
                    result = payload
                if stdio_mode:
                    result = {{"jsonrpc": "2.0", "id": request_id, "result": result}}
                print(json.dumps(result, ensure_ascii=False, sort_keys=False), flush=True)
                if stdio_mode and mode == "unknown-rc1":
                    raise SystemExit(1)
                if not stdio_mode and mode in ("refused", "indeterminate", "ok-rc1", "unknown-rc1"):
                    raise SystemExit(1)
                """
            ),
            encoding="utf-8",
        )
        self.launcher.chmod(0o755)
        document = {
            "tools": [
                {
                    "name": "jackal_echo",
                    "description": "Echo fixture data.",
                    "arguments": {
                        "payload": {"type": "object", "required": True, "help": "Fixture payload."},
                        "mode": {"type": "string", "required": False, "help": "Fixture mode."},
                        "pid_file": {"type": "string", "required": False, "help": "Fixture PID file."},
                        "release_file": {"type": "string", "required": False, "help": "Fixture leader release file."},
                    },
                    "returns": {},
                },
                {
                    "name": "jackal_second",
                    "description": "Second fixture tool.",
                    "arguments": {
                        "payload": {"type": "object", "required": True, "help": "Fixture payload."},
                        "mode": {"type": "string", "required": False, "help": "Fixture mode."},
                        "pid_file": {"type": "string", "required": False, "help": "Fixture PID file."},
                        "release_file": {"type": "string", "required": False, "help": "Fixture leader release file."},
                    },
                    "returns": {},
                },
            ]
        }
        self.tool_document = document
        self.tool_fixture = hermes / "test-tools.json"
        self.tool_fixture.write_text(json.dumps(document), encoding="utf-8")
        self.definitions = adapter.build_tool_definitions(document, expected_count=2)
        self.server = adapter.MCPServer(
            runtime_root=self.runtime,
            launcher=self.launcher,
            tool_definitions=self.definitions,
            runtime_environment=TEST_RUNTIME_ENVIRONMENT,
            tool_timeout=2.0,
            stdout_limit=4096,
            stderr_limit=4096,
            terminate_grace=0.1,
        )

    async def asyncTearDown(self):
        await self.server.close()
        leaked = []
        for pid_file in self.pid_files:
            for pid in self._read_pids(pid_file):
                if await self._wait_not_live(pid):
                    leaked.append(pid)
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        for pid in leaked:
            await self._wait_not_live(pid)
        self.assertEqual(leaked, [], f"fake runtime processes leaked: {leaked}")

    async def test_backend_call_ignores_hostile_caller_path_python3(self):
        hostile = Path(self.temporary.name) / "hostile"
        hostile.mkdir()
        attacked = Path(self.temporary.name) / "attacker-ran"
        fake_python = hostile / "python3"
        fake_python.write_text(
            "#!/bin/sh\n"
            f"printf attacked > {str(attacked)!r}\n"
            "echo '{\"status\":\"checked\",\"origin\":\"hostile-path\"}'\n",
            encoding="utf-8",
        )
        fake_python.chmod(0o755)
        entry = Path(self.temporary.name) / "legitimate-backend.py"
        entry.write_text(
            "import json, sys\n"
            "request = json.loads(sys.stdin.buffer.read())\n"
            "print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], "
            "'result': {'status': 'checked', 'origin': 'selected-python'}}))\n",
            encoding="utf-8",
        )
        launcher = Path(self.temporary.name) / "bare-python-launcher"
        launcher.write_text(
            "#!/bin/sh\n"
            f"exec python3 -I -S -B {str(entry)!r} \"$@\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        server = adapter.MCPServer(
            runtime_root=self.runtime,
            launcher=launcher,
            tool_definitions=self.definitions,
            runtime_environment=real_provisioner.runtime_subprocess_environment({}),
            tool_timeout=2.0,
            stdout_limit=4096,
            stderr_limit=4096,
            terminate_grace=0.1,
        )
        try:
            with mock.patch.dict(os.environ, {"PATH": str(hostile)}, clear=False):
                response = await server.handle_message(self._call(901))
        finally:
            await server.close()

        self.assertEqual(
            response["result"]["structuredContent"],
            {"status": "checked", "origin": "selected-python"},
        )
        self.assertFalse(attacked.exists())

    async def test_one_request_can_launch_multiple_serial_backend_processes(self):
        state = adapter._CallState(request_id="multi-delegation")
        first = self.server._invoke_backend_sync(
            state, "jackal_echo", {"payload": {"delegation": "first"}},
        )
        second = self.server._invoke_backend_sync(
            state, "jackal_echo", {"payload": {"delegation": "second"}},
        )

        self.assertEqual(first, {"delegation": "first"})
        self.assertEqual(second, {"delegation": "second"})
        self.assertTrue(state.reaped)
        self.assertIsNone(state.process)
        self.assertIsNone(state.runner)

    async def test_replay_sized_backend_arguments_are_streamed_over_stdin(self):
        response = await self.server.handle_message(
            self._call(
                "large-backend-input",
                payload={"receipt": "x" * adapter.MAX_CATALOG_BYTES},
                mode="accept-large",
            )
        )

        self.assertEqual(
            response["result"]["structuredContent"],
            {"status": "checked", "accepted": True},
        )

    async def test_active_call_flood_refuses_ordinary_busy_and_recovers(self):
        limited = adapter.MCPServer(
            runtime_root=self.runtime,
            launcher=self.launcher,
            tool_definitions=self.definitions,
            runtime_environment=TEST_RUNTIME_ENVIRONMENT,
            max_active_calls=2,
            # The capacity assertion deliberately floods 100 ordinary busy
            # responses before cancellation. Keep its unrelated backend
            # timeout well outside that scheduler/load-sensitive window.
            tool_timeout=10.0,
            stdout_limit=4096,
            stderr_limit=4096,
            terminate_grace=0.1,
        )
        pid_file = self._new_pid_file("capacity-tree.pid")
        first = asyncio.create_task(
            limited.handle_message(
                self._call(910, mode="hang", pid_file=pid_file)
            )
        )
        try:
            await self._wait_for_pids(pid_file, count=2)
            second = asyncio.create_task(
                limited.handle_message(
                    self._call(911, payload={"status": "checked", "slot": 2})
                )
            )
            deadline = time.monotonic() + 1.0
            while len(limited._active) != 2 and time.monotonic() < deadline:
                await asyncio.sleep(0)
            self.assertEqual(len(limited._active), 2)

            flood = await asyncio.gather(
                *(
                    limited.handle_message(
                        self._call(request_id, payload={"request": request_id})
                    )
                    for request_id in range(912, 1012)
                )
            )
            for response in flood:
                self.assertNotIn("error", response)
                self.assertEqual(
                    response["result"]["structuredContent"],
                    {"status": "refused", "reason": "plugin-busy"},
                )
            self.assertEqual(len(limited._active), 2)

            self.assertIsNone(await limited.handle_message(self._cancel(910)))
            first_response, second_response = await asyncio.gather(first, second)
            self.assertEqual(first_response["error"]["code"], adapter.REQUEST_CANCELLED)
            self.assertEqual(
                second_response["result"]["structuredContent"],
                {"status": "checked", "slot": 2},
            )
            self.assertEqual(limited._active, {})

            failed = await limited.handle_message(self._call(1012, mode="invalid"))
            self.assertEqual(failed["error"]["code"], adapter.BACKEND_ERROR)
            self.assertEqual(limited._active, {})
            recovered = await limited.handle_message(
                self._call(1013, payload={"status": "checked", "recovered": True})
            )
            self.assertEqual(
                recovered["result"]["structuredContent"],
                {"status": "checked", "recovered": True},
            )
        finally:
            if not first.done():
                await limited.handle_message(self._cancel(910))
                await asyncio.gather(first, return_exceptions=True)
            await limited.close()

    async def test_transport_task_capacity_applies_backpressure(self):
        gates = [asyncio.Event(), asyncio.Event()]
        tasks = {asyncio.create_task(gate.wait()) for gate in gates}
        waiter = asyncio.create_task(
            adapter._wait_for_transport_capacity(tasks, max_tasks=2)
        )
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())

        gates[0].set()
        await asyncio.wait_for(waiter, timeout=1.0)
        self.assertLess(len(tasks), 2)

        gates[1].set()
        await asyncio.gather(*tasks, return_exceptions=True)

        async def fail_handler():
            raise RuntimeError("fixture handler failure")

        failed = asyncio.create_task(fail_handler())
        failed_tasks = {failed}
        await asyncio.sleep(0)
        await adapter._wait_for_transport_capacity(failed_tasks, max_tasks=1)
        self.assertEqual(failed_tasks, set())

    async def test_response_queue_refuses_overflow_without_waiting(self):
        queue = adapter._BoundedResponseQueue(max_bytes=8)
        await queue.put(b"12345678")

        with self.assertRaisesRegex(adapter._ResponseQueueFull, "capacity"):
            await asyncio.wait_for(queue.put(b"x"), timeout=0.1)

        self.assertEqual(await queue.get(), b"12345678")
        await queue.close()

    def _request(self, request_id, method, params=None):
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        return message

    def _call(
        self,
        request_id,
        *,
        name="jackal_echo",
        payload=None,
        mode=None,
        pid_file=None,
        release_file=None,
    ):
        arguments = {"payload": {} if payload is None else payload}
        if mode is not None:
            arguments["mode"] = mode
        if pid_file is not None:
            arguments["pid_file"] = str(pid_file)
        if release_file is not None:
            arguments["release_file"] = str(release_file)
        return self._request(
            request_id,
            "tools/call",
            {"name": name, "arguments": arguments},
        )

    def _cancel(self, request_id, *, include_meta=False):
        params = {"requestId": request_id, "reason": "test cancellation"}
        if include_meta:
            params["_meta"] = {"progressToken": "cancel-fixture"}
        return {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": params,
        }

    async def _spawn_stdio_server(self, runtime_owner_path=None):
        driver = textwrap.dedent(
            """\
            import asyncio
            import json
            import sys
            from pathlib import Path
            from plugins.jackel.mcp import server as adapter
            from plugins.jackel.scripts import provision_runtime

            runtime = Path(sys.argv[1])
            launcher = Path(sys.argv[2])
            document = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
            runtime_owner_path = Path(sys.argv[4]) if sys.argv[4] else None

            class RuntimeOwner:
                def close(self):
                    import shutil
                    shutil.rmtree(runtime_owner_path)

            definitions = adapter.build_tool_definitions(document, expected_count=2)
            instance = adapter.MCPServer(
                runtime_root=runtime,
                launcher=launcher,
                tool_definitions=definitions,
                runtime_environment=provision_runtime.runtime_subprocess_environment({}),
                tool_timeout=15.0,
                stdout_limit=256,
                stderr_limit=256,
                terminate_grace=0.05,
                leader_poll_interval=10.0,
                runtime_owner=(RuntimeOwner() if runtime_owner_path else None),
            )
            asyncio.run(adapter._serve_stdio(instance))
            """
        )
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-B",
            "-c",
            driver,
            str(self.runtime),
            str(self.launcher),
            str(self.tool_fixture),
            "" if runtime_owner_path is None else str(runtime_owner_path),
            cwd=str(REPO_ROOT),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def _spawn_transport_fixture(self, mode, marker):
        driver = textwrap.dedent(
            """\
            import asyncio
            import json
            import sys
            from pathlib import Path
            from plugins.jackel.mcp import server as adapter

            mode = sys.argv[1]
            marker = Path(sys.argv[2])

            if mode in {"oversize-queue-closed", "oversize-queue-full"}:
                async def refuse_oversize_response(unused_queue, unused_payload):
                    if mode == "oversize-queue-closed":
                        raise adapter._ResponseQueueClosed("fixture queue closed")
                    raise adapter._ResponseQueueFull("fixture queue full")

                adapter._BoundedResponseQueue.put = refuse_oversize_response

            class FixtureServer:
                async def handle_line(self, line):
                    message = json.loads(line)
                    if mode == "nonreader" and message.get("method") == "notifications/cancelled":
                        marker.write_text("cancelled\\n", encoding="utf-8")
                        return None
                    if mode == "exception" and message.get("id") == 0:
                        raise RuntimeError("fixture handler failure")
                    payload = "x" * (512 * 1024) if mode == "nonreader" else "ok"
                    return {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "result": {"payload": payload},
                    }

                async def close(self):
                    with marker.open("a", encoding="utf-8") as handle:
                        handle.write("closed\\n")

            asyncio.run(adapter._serve_stdio(FixtureServer()))
            """
        )
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-B",
            "-c",
            driver,
            mode,
            str(marker),
            cwd=str(REPO_ROOT),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    def _new_pid_file(self, name):
        path = Path(self.temporary.name) / name
        self.pid_files.append(path)
        return path

    def _read_pids(self, path):
        if not path.exists():
            return []
        return sorted({int(line) for line in path.read_text().splitlines() if line.strip()})

    async def _wait_for_pids(self, path, count=3):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            pids = self._read_pids(path)
            if len(pids) >= count:
                return pids
            await asyncio.sleep(0.02)
        self.fail(f"fixture did not publish {count} PIDs: {self._read_pids(path)}")

    async def _wait_for_exited_leader_with_live_descendants(self, pids):
        deadline = time.monotonic() + 3
        leader = None
        while time.monotonic() < deadline:
            for pid in pids:
                try:
                    leader = os.getpgid(pid)
                    break
                except ProcessLookupError:
                    continue
            if leader is not None:
                descendants = [pid for pid in pids if pid != leader]
                if (
                    not self._process_is_live(leader)
                    and len(descendants) >= 2
                    and all(self._process_is_live(pid) for pid in descendants)
                ):
                    return leader, descendants
            await asyncio.sleep(0.01)
        self.fail(
            "fixture never reached exited-leader/live-descendants state: "
            f"leader={leader} pids={pids}"
        )

    def _process_is_live(self, pid):
        result = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        state = result.stdout.strip()
        return result.returncode == 0 and bool(state) and not state.startswith("Z")

    async def _wait_not_live(self, pid):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not self._process_is_live(pid):
                return False
            await asyncio.sleep(0.03)
        return self._process_is_live(pid)

    async def test_initialize_ping_notification_and_full_tools_list(self):
        initialized = await self.server.handle_message(
            self._request(
                "init-1",
                "initialize",
                {
                    "protocolVersion": adapter.LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1"},
                },
            )
        )
        self.assertEqual(initialized["jsonrpc"], "2.0")
        self.assertEqual(initialized["id"], "init-1")
        self.assertEqual(initialized["result"]["protocolVersion"], adapter.LATEST_PROTOCOL_VERSION)
        self.assertEqual(
            initialized["result"]["capabilities"],
            {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
            },
        )
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "jackel-codex")

        self.assertIsNone(
            await self.server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {"_meta": {"progressToken": "initialized-fixture"}},
                }
            )
        )
        ping = await self.server.handle_message(
            self._request(2, "ping", {"_meta": {"progressToken": 2}})
        )
        self.assertEqual(ping["result"], {})
        listed = await self.server.handle_message(
            self._request(
                3,
                "tools/list",
                {"cursor": "opaque-cursor", "_meta": {"progressToken": "list-fixture"}},
            )
        )
        self.assertEqual(listed["result"]["tools"], list(self.definitions))

        called = self._call(4, payload={"status": "checked", "meta": "not-forwarded"})
        called["params"]["_meta"] = {"progressToken": "call-fixture"}
        response = await self.server.handle_message(called)
        self.assertEqual(
            response["result"]["structuredContent"],
            {"status": "checked", "meta": "not-forwarded"},
        )

        for request_id, method, params in (
            (5, "ping", {"_meta": []}),
            (6, "tools/list", {"cursor": 7}),
            (7, "tools/call", {"name": "jackal_echo", "arguments": {"payload": {}}, "_meta": []}),
        ):
            with self.subTest(method=method, params=params):
                refused = await self.server.handle_message(self._request(request_id, method, params))
                self.assertEqual(refused["error"]["code"], -32602)

    async def test_success_refusal_and_indeterminate_preserve_backend_objects(self):
        cases = (
            ("echo", {"status": "checked", "nested": {"z": 2, "a": [1, True]}}),
            ("refused", {"x": 1}),
            ("indeterminate", {"x": 2}),
        )
        for request_id, (mode, payload) in enumerate(cases, start=10):
            with self.subTest(mode=mode):
                response = await self.server.handle_message(
                    self._call(request_id, payload=payload, mode=mode)
                )
                expected = payload
                if mode == "refused":
                    expected = {"status": "refused", "reason": "fixture-refusal", "input": payload}
                elif mode == "indeterminate":
                    expected = {
                        "status": "indeterminate",
                        "reason": "fixture-indeterminate",
                        "input": payload,
                    }
                self.assertEqual(response["result"]["structuredContent"], expected)
                self.assertNotIn("isError", response["result"])
                self.assertEqual(json.loads(response["result"]["content"][0]["text"]), expected)

    async def test_backend_owns_known_tool_argument_schema_refusals_with_exact_parity(self):
        cases = (
            {},
            {"payload": {}, "extra": {"nested": [1, True, None]}},
            {"payload": "wrong-backend-type"},
        )
        for request_id, arguments in enumerate(cases, start=90):
            with self.subTest(arguments=arguments):
                compact = json.dumps(
                    arguments, ensure_ascii=False, allow_nan=False,
                    sort_keys=True, separators=(",", ":"),
                )
                # Keep this tiny fixture invocation synchronous.  The host's
                # current asyncio global executor does not reliably shut down,
                # and the production adapter intentionally owns its worker
                # threads instead of depending on that global executor.
                direct_process = subprocess.run(
                    [str(self.launcher), "call", "jackal_echo", compact],
                    cwd=self.runtime, capture_output=True, text=True, check=False,
                )
                self.assertEqual(direct_process.returncode, 1)
                direct = json.loads(direct_process.stdout)

                response = await self.server.handle_message(
                    self._request(
                        request_id, "tools/call",
                        {"name": "jackal_echo", "arguments": copy.deepcopy(arguments)},
                    )
                )

                self.assertNotIn("error", response)
                self.assertEqual(response["result"]["structuredContent"], direct)
                self.assertEqual(
                    json.loads(response["result"]["content"][0]["text"]), direct,
                )
                self.assertEqual(direct["status"], "refused")
                self.assertEqual(direct["reason"], "plugin-args-schema")
                self.assertEqual(direct["arguments"], arguments)

    async def test_rc1_ok_is_semantic_success_but_unknown_or_malformed_rc1_fails_closed(self):
        claim = {
            "status": "ok",
            "bundle": {
                "claim_class": "formal-bounded",
                "receipt_sha256": "a" * 64,
            },
        }
        response = await self.server.handle_message(
            self._call(14, payload=claim, mode="ok-rc1")
        )
        self.assertEqual(response["result"]["structuredContent"], claim)
        self.assertNotIn("isError", response["result"])

        for request_id, mode, payload in (
            (15, "unknown-rc1", {"status": "unexpected", "bundle": {}}),
            (16, "invalid-rc1", {}),
        ):
            with self.subTest(mode=mode):
                refused = await self.server.handle_message(
                    self._call(request_id, payload=payload, mode=mode)
                )
                self.assertEqual(refused["error"]["code"], adapter.BACKEND_ERROR)

    async def test_invalid_or_multiple_backend_json_fails_closed(self):
        for request_id, mode in (
            (20, "invalid"),
            (21, "multiple"),
            (22, "duplicate"),
            (23, "nan"),
        ):
            with self.subTest(mode=mode):
                response = await self.server.handle_message(self._call(request_id, mode=mode))
                self.assertIn("error", response)
                self.assertEqual(response["error"]["code"], adapter.BACKEND_ERROR)
                self.assertNotIn("Traceback", json.dumps(response))

    async def test_stderr_is_bounded_and_never_enters_protocol_result(self):
        response = await self.server.handle_message(
            self._call(30, payload={"status": "checked"}, mode="stderr")
        )
        self.assertEqual(response["result"]["structuredContent"], {"status": "checked"})
        self.assertNotIn("SENSITIVE-BACKEND-STDERR", json.dumps(response))

    async def test_malformed_requests_and_adapter_owned_argument_shape_fail_closed(self):
        malformed_line = await self.server.handle_line(b"{not-json\n")
        self.assertEqual(malformed_line["error"]["code"], -32700)
        self.assertIsNone(malformed_line["id"])

        cases = (
            ({"jsonrpc": "1.0", "id": 1, "method": "ping"}, -32600),
            ({"jsonrpc": "2.0", "id": True, "method": "ping"}, -32600),
            (self._request(2, "missing/method", {}), -32601),
            (self._call(3, payload={"x": 1}) | {"extra": True}, -32600),
            (self._request(4, "tools/call", {"name": "unknown", "arguments": {}}), -32602),
            (
                self._request(
                    5,
                    "tools/call",
                    {"name": "jackal_echo", "arguments": []},
                ),
                -32602,
            ),
        )
        for message, code in cases:
            with self.subTest(message=message):
                response = await self.server.handle_message(message)
                self.assertEqual(response["error"]["code"], code)
                self.assertLessEqual(len(json.dumps(response)), adapter.MAX_ERROR_RESPONSE_BYTES)

        oversized = b"{" + b"x" * adapter.MAX_REQUEST_LINE_BYTES + b"}\n"
        response = await self.server.handle_line(oversized)
        self.assertEqual(response["error"]["code"], -32600)

        duplicate_key = await self.server.handle_line(
            b'{"jsonrpc":"2.0","id":8,"id":9,"method":"ping"}\n'
        )
        self.assertEqual(duplicate_key["error"]["code"], -32700)

        unterminated = await self.server.handle_line(
            b'{"jsonrpc":"2.0","id":9,"method":"ping"}'
        )
        self.assertEqual(unterminated["error"]["code"], -32600)
        self.assertIsNone(unterminated["id"])

        replay_sized = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 10,
                    "method": "ping",
                    "params": {"_meta": {"receipt_fixture": "x" * adapter.MAX_CATALOG_BYTES}},
                },
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        self.assertLess(len(replay_sized), adapter.MAX_REQUEST_LINE_BYTES)
        replay_response = await self.server.handle_line(replay_sized)
        self.assertEqual(replay_response["result"], {})

    async def test_deep_json_and_recursion_failure_are_bounded_parse_errors(self):
        expected_depth_limit = getattr(adapter, "MAX_JSON_DEPTH", 64)
        nested = (
            b"[" * (expected_depth_limit + 1)
            + b"0"
            + b"]" * (expected_depth_limit + 1)
            + b"\n"
        )
        response = await self.server.handle_line(nested)
        self.assertEqual(response["error"]["code"], adapter.PARSE_ERROR)
        self.assertLessEqual(len(json.dumps(response)), adapter.MAX_ERROR_RESPONSE_BYTES)

        with mock.patch.object(adapter, "_strict_json_loads", side_effect=RecursionError):
            response = await self.server.handle_line(
                b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
            )
        self.assertEqual(response["error"]["code"], adapter.PARSE_ERROR)

    async def test_invalid_request_shape_preserves_a_valid_detectable_id(self):
        cases = (
            ({"jsonrpc": "1.0", "id": "correlate-me", "method": "ping"}, "correlate-me"),
            ({"jsonrpc": "2.0", "id": 17, "method": "ping", "extra": True}, 17),
            ({"jsonrpc": "1.0", "id": True, "method": "ping"}, None),
            ({"jsonrpc": "1.0", "id": None, "method": "ping"}, None),
        )
        for message, expected_id in cases:
            with self.subTest(message=message):
                response = await self.server.handle_message(message)
                self.assertEqual(response["error"]["code"], -32600)
                self.assertEqual(response["id"], expected_id)

    async def test_matching_cancellation_kills_process_tree_and_next_call_recovers(self):
        pid_file = self._new_pid_file("cancel-tree.pids")
        anchored_server = adapter.MCPServer(
            runtime_root=self.runtime,
            launcher=self.launcher,
            tool_definitions=self.definitions,
            runtime_environment=TEST_RUNTIME_ENVIRONMENT,
            tool_timeout=2.0,
            stdout_limit=4096,
            stderr_limit=4096,
            terminate_grace=0.1,
            leader_poll_interval=1.0,
        )
        self.addAsyncCleanup(anchored_server.close)
        task = asyncio.create_task(
            anchored_server.handle_message(
                self._call(40, mode="orphan-hold-exit", pid_file=pid_file)
            )
        )
        pids = await self._wait_for_pids(pid_file)
        unused_leader, descendants = await self._wait_for_exited_leader_with_live_descendants(
            pids
        )
        state = anchored_server._active[40]
        observation_deadline = time.monotonic() + 2
        while state.leader_status is None and not task.done():
            if time.monotonic() >= observation_deadline:
                self.fail("backend runner did not observe the exited leader")
            await asyncio.sleep(0.005)
        self.assertIsNotNone(state.leader_status)
        self.assertFalse(task.done())
        started = time.monotonic()
        self.assertIsNone(await anchored_server.handle_message(self._cancel(40)))
        response = await asyncio.wait_for(task, timeout=2)
        elapsed = time.monotonic() - started
        self.assertEqual(response["error"]["code"], adapter.REQUEST_CANCELLED)
        self.assertGreaterEqual(elapsed, anchored_server.terminate_grace * 0.75)
        self.assertTrue(state.term_sent)
        self.assertTrue(state.kill_sent)
        self.assertEqual(len(descendants), 2)
        for pid in pids:
            self.assertFalse(await self._wait_not_live(pid), f"cancelled process survived: {pid}")

        recovered = await anchored_server.handle_message(
            self._call(41, payload={"status": "checked", "after": "cancel"})
        )
        self.assertEqual(
            recovered["result"]["structuredContent"],
            {"status": "checked", "after": "cancel"},
        )

    async def test_meta_bearing_cancellation_is_effective_and_scoped(self):
        pid_file = self._new_pid_file("meta-cancel-tree.pids")
        task = asyncio.create_task(
            self.server.handle_message(
                self._call(42, mode="resistant-tree", pid_file=pid_file)
            )
        )
        pids = await self._wait_for_pids(pid_file)
        self.assertIsNone(
            await self.server.handle_message(self._cancel(42, include_meta=True))
        )
        response = await asyncio.wait_for(task, timeout=2)
        self.assertEqual(response["error"]["code"], adapter.REQUEST_CANCELLED)
        for pid in pids:
            self.assertFalse(await self._wait_not_live(pid), f"meta-cancel survived: {pid}")

    async def test_stale_cancellation_cannot_kill_a_different_active_request(self):
        first = await self.server.handle_message(self._call(50, payload={"first": True}))
        self.assertIn("result", first)
        active = asyncio.create_task(
            self.server.handle_message(self._call(51, payload={"survived": True}, mode="slow"))
        )
        await asyncio.sleep(0.08)
        self.assertIsNone(await self.server.handle_message(self._cancel(50)))
        self.assertIsNone(await self.server.handle_message(self._cancel(999)))
        response = await asyncio.wait_for(active, timeout=2)
        self.assertEqual(response["result"]["structuredContent"], {"survived": True})

    async def test_waiting_call_can_be_cancelled_without_touching_lock_holder(self):
        holder = asyncio.create_task(
            self.server.handle_message(self._call(60, payload={"holder": True}, mode="slow"))
        )
        await asyncio.sleep(0.08)
        waiting = asyncio.create_task(
            self.server.handle_message(self._call(61, payload={"waiting": True}))
        )
        await asyncio.sleep(0.05)
        self.assertIsNone(await self.server.handle_message(self._cancel(61)))
        waiting_response = await asyncio.wait_for(waiting, timeout=1)
        self.assertEqual(waiting_response["error"]["code"], adapter.REQUEST_CANCELLED)
        holder_response = await asyncio.wait_for(holder, timeout=2)
        self.assertEqual(holder_response["result"]["structuredContent"], {"holder": True})

    async def test_duplicate_active_request_id_is_rejected_but_string_and_integer_ids_differ(self):
        holder = asyncio.create_task(
            self.server.handle_message(self._call(80, payload={"holder": True}, mode="slow"))
        )
        await asyncio.sleep(0.08)
        duplicate = await self.server.handle_message(self._call(80, payload={"duplicate": True}))
        self.assertEqual(duplicate["error"]["code"], -32600)

        string_id = asyncio.create_task(
            self.server.handle_message(self._call("80", payload={"string": True}))
        )
        holder_response = await asyncio.wait_for(holder, timeout=2)
        string_response = await asyncio.wait_for(string_id, timeout=2)
        self.assertEqual(holder_response["result"]["structuredContent"], {"holder": True})
        self.assertEqual(string_response["result"]["structuredContent"], {"string": True})

    async def test_timeout_and_output_limit_kill_backend_and_return_bounded_errors(self):
        pid_file = self._new_pid_file("timeout-tree.pids")
        timeout_server = adapter.MCPServer(
            runtime_root=self.runtime,
            launcher=self.launcher,
            tool_definitions=self.definitions,
            runtime_environment=TEST_RUNTIME_ENVIRONMENT,
            tool_timeout=0.5,
            stdout_limit=256,
            stderr_limit=256,
            terminate_grace=0.05,
            leader_poll_interval=1.0,
        )
        self.addAsyncCleanup(timeout_server.close)
        timeout_task = asyncio.create_task(
            timeout_server.handle_message(
                self._call(70, mode="orphan-hold-crash", pid_file=pid_file)
            )
        )
        pids = await self._wait_for_pids(pid_file)
        await self._wait_for_exited_leader_with_live_descendants(pids)
        timeout_response = await asyncio.wait_for(timeout_task, timeout=2)
        self.assertEqual(timeout_response["error"]["code"], adapter.BACKEND_TIMEOUT)
        for pid in pids:
            self.assertFalse(await self._wait_not_live(pid), f"timed-out process survived: {pid}")

        output_pid_file = self._new_pid_file("output-tree.pids")
        # The output-limit case exercises a different terminal condition after
        # the leader has exited. Give it an independent timeout budget so CI
        # scheduling cannot make the timeout race win before the orphan emits
        # its deliberately oversized stdout.
        output_server = adapter.MCPServer(
            runtime_root=self.runtime,
            launcher=self.launcher,
            tool_definitions=self.definitions,
            runtime_environment=TEST_RUNTIME_ENVIRONMENT,
            tool_timeout=2.0,
            stdout_limit=256,
            stderr_limit=256,
            terminate_grace=0.05,
            leader_poll_interval=1.0,
        )
        self.addAsyncCleanup(output_server.close)
        output_task = asyncio.create_task(
            output_server.handle_message(
                self._call(71, mode="orphan-output-exit", pid_file=output_pid_file)
            )
        )
        output_pids = await self._wait_for_pids(output_pid_file)
        await self._wait_for_exited_leader_with_live_descendants(output_pids)
        output_response = await asyncio.wait_for(output_task, timeout=3)
        self.assertEqual(output_response["error"]["code"], adapter.BACKEND_ERROR)
        self.assertLessEqual(len(json.dumps(output_response)), adapter.MAX_ERROR_RESPONSE_BYTES)
        for pid in output_pids:
            self.assertFalse(await self._wait_not_live(pid), f"output-limit process survived: {pid}")

    async def test_server_close_cancels_and_reaps_an_active_process_tree(self):
        pid_file = self._new_pid_file("close-tree.pids")
        owner_close_observations = []
        state_reference = {}
        owner = mock.Mock()
        owner.close.side_effect = lambda: owner_close_observations.append(
            state_reference["state"].reaped
        )
        anchored_server = adapter.MCPServer(
            runtime_root=self.runtime,
            launcher=self.launcher,
            tool_definitions=self.definitions,
            runtime_environment=TEST_RUNTIME_ENVIRONMENT,
            tool_timeout=2.0,
            stdout_limit=4096,
            stderr_limit=4096,
            terminate_grace=0.05,
            leader_poll_interval=1.0,
            runtime_owner=owner,
        )
        self.addAsyncCleanup(anchored_server.close)
        task = asyncio.create_task(
            anchored_server.handle_message(
                self._call(90, mode="orphan-hold-exit", pid_file=pid_file)
            )
        )
        pids = await self._wait_for_pids(pid_file)
        await self._wait_for_exited_leader_with_live_descendants(pids)
        state_reference["state"] = anchored_server._active[90]
        await anchored_server.close()
        response = await asyncio.wait_for(task, timeout=2)
        self.assertEqual(response["error"]["code"], adapter.REQUEST_CANCELLED)
        for pid in pids:
            self.assertFalse(await self._wait_not_live(pid), f"closed process survived: {pid}")
        self.assertEqual(owner_close_observations, [True])
        owner.close.assert_called_once_with()

    async def test_runtime_snapshot_cleanup_failure_remains_retryable(self):
        owner = types.SimpleNamespace(
            close=mock.Mock(side_effect=(OSError("fixture cleanup failure"), None))
        )
        server = adapter.MCPServer(
            runtime_root=self.runtime,
            launcher=self.launcher,
            tool_definitions=self.definitions,
            runtime_environment=TEST_RUNTIME_ENVIRONMENT,
            runtime_owner=owner,
            tool_timeout=2.0,
            stdout_limit=4096,
            stderr_limit=4096,
            terminate_grace=0.1,
        )

        with self.assertRaises(adapter.BackendFailure):
            await server.close()
        self.assertIs(server._runtime_owner, owner)

        await server.close()
        self.assertIsNone(server._runtime_owner)
        self.assertEqual(owner.close.call_count, 2)

    async def test_actual_stdio_cancellation_is_responsive_stdout_only_and_recovers(self):
        pid_file = self._new_pid_file("stdio-cancel-tree.pids")
        release_file = Path(f"{pid_file}.release")
        process = await self._spawn_stdio_server()
        self.assertIsNotNone(process.stdin)
        self.assertIsNotNone(process.stdout)
        self.assertIsNotNone(process.stderr)
        call = self._call(
            100,
            mode="orphan-hold-exit",
            pid_file=pid_file,
            release_file=release_file,
        )
        process.stdin.write(json.dumps(call, separators=(",", ":")).encode() + b"\n")
        await process.stdin.drain()
        pids = await self._wait_for_pids(pid_file)
        release_file.write_text("exit\n", encoding="utf-8")
        await self._wait_for_exited_leader_with_live_descendants(pids)

        cancellation = self._cancel(100, include_meta=True)
        process.stdin.write(json.dumps(cancellation, separators=(",", ":")).encode() + b"\n")
        await process.stdin.drain()
        response = json.loads(await asyncio.wait_for(process.stdout.readline(), timeout=2))
        self.assertEqual(response["id"], 100)
        self.assertEqual(response["error"]["code"], adapter.REQUEST_CANCELLED)

        process.stdin.write(
            b'{"jsonrpc":"2.0","id":101,"method":"ping","params":{"_meta":{}}}\n'
        )
        await process.stdin.drain()
        ping = json.loads(await asyncio.wait_for(process.stdout.readline(), timeout=2))
        self.assertEqual(ping, {"jsonrpc": "2.0", "id": 101, "result": {}})
        process.stdin.close()
        await process.stdin.wait_closed()
        self.assertEqual(await asyncio.wait_for(process.wait(), timeout=2), 0)
        self.assertEqual(await process.stderr.read(), b"")
        self.assertEqual(await process.stdout.read(), b"")
        for pid in pids:
            self.assertFalse(await self._wait_not_live(pid), f"stdio-cancel survived: {pid}")

    async def test_nonreading_stdout_does_not_block_cancellation_or_eof(self):
        marker = Path(self.temporary.name) / "nonreader.marker"
        process = await self._spawn_transport_fixture("nonreader", marker)
        try:
            large = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
            cancel = {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": 1},
            }
            process.stdin.write(json.dumps(large).encode() + b"\n")
            process.stdin.write(json.dumps(cancel).encode() + b"\n")
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()
            deadline = asyncio.get_running_loop().time() + 2
            while process.returncode is None and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.01)
            if process.returncode is None:
                raise TimeoutError("stdio server did not exit while stdout was unread")
            return_code = process.returncode
        except BaseException:
            process.kill()
            await asyncio.wait_for(process.communicate(), timeout=2)
            raise
        self.assertEqual(return_code, 0)
        self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["cancelled", "closed"])
        unused_stdout, stderr = await process.communicate()
        self.assertEqual(stderr, b"")

    async def test_oversize_line_queue_shutdown_is_bounded_and_clean(self):
        oversized = b"x" * (adapter.MAX_REQUEST_LINE_BYTES + 2) + b"\n"
        for mode in ("oversize-queue-closed", "oversize-queue-full"):
            with self.subTest(mode=mode):
                marker = Path(self.temporary.name) / f"{mode}.marker"
                process = await self._spawn_transport_fixture(mode, marker)
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(oversized), timeout=2
                )
                self.assertEqual(process.returncode, 0)
                self.assertEqual(stdout, b"")
                self.assertEqual(stderr, b"")
                self.assertEqual(
                    marker.read_text(encoding="utf-8").splitlines(), ["closed"]
                )

    async def test_closed_stdout_reader_stops_stdio_without_waiting_for_stdin(self):
        marker = Path(self.temporary.name) / "writer-loss.marker"
        process = await self._spawn_transport_fixture("normal", marker)
        pipe_transport = process._transport.get_pipe_transport(1)
        self.assertIsNotNone(pipe_transport)
        pipe_transport.close()
        try:
            self.assertIsNotNone(process.stdin)
            await asyncio.wait_for(process.wait(), timeout=1)
        except BaseException:
            if process.stdin is not None:
                process.stdin.close()
            if process.returncode is None:
                process.kill()
            await asyncio.wait_for(process.wait(), timeout=2)
            raise

        self.assertEqual(process.returncode, 0)
        self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["closed"])

    async def test_handler_exception_is_bounded_and_stdio_recovers(self):
        marker = Path(self.temporary.name) / "handler.marker"
        process = await self._spawn_transport_fixture("exception", marker)
        requests = b"".join(
            json.dumps({"jsonrpc": "2.0", "id": index, "method": "ping"}).encode()
            + b"\n"
            for index in range(adapter.MAX_TRANSPORT_TASKS + 4)
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(requests), timeout=3)

        self.assertEqual(process.returncode, 0)
        self.assertEqual(stderr, b"")
        responses = [json.loads(line) for line in stdout.splitlines()]
        self.assertEqual(len(responses), adapter.MAX_TRANSPORT_TASKS + 4)
        self.assertEqual(responses[0]["error"]["code"], adapter.INTERNAL_ERROR)
        self.assertEqual(responses[-1]["result"], {"payload": "ok"})
        self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["closed"])

    async def test_actual_stdio_unterminated_eof_refuses_without_execution(self):
        pid_file = self._new_pid_file("unterminated-eof-tree.pids")
        process = await self._spawn_stdio_server()
        call = self._call(110, mode="resistant-tree", pid_file=pid_file)
        raw = json.dumps(call, separators=(",", ":")).encode()
        stdout, stderr = await asyncio.wait_for(process.communicate(input=raw), timeout=2)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(stderr, b"")
        records = stdout.splitlines()
        self.assertEqual(len(records), 1)
        response = json.loads(records[0])
        self.assertEqual(response["error"]["code"], -32600)
        self.assertIsNone(response["id"])
        self.assertFalse(pid_file.exists(), "unterminated record executed the backend")

    async def test_actual_stdio_eof_closes_resistant_process_tree(self):
        pid_file = self._new_pid_file("stdio-eof-tree.pids")
        release_file = Path(f"{pid_file}.release")
        runtime_owner_path = Path(self.temporary.name) / "stdio-owned-snapshot"
        runtime_owner_path.mkdir()
        (runtime_owner_path / "owned-byte").write_text("fixture\n", encoding="utf-8")
        process = await self._spawn_stdio_server(runtime_owner_path)
        self.assertIsNotNone(process.stdin)
        call = self._call(
            120,
            mode="orphan-hold-crash",
            pid_file=pid_file,
            release_file=release_file,
        )
        process.stdin.write(json.dumps(call, separators=(",", ":")).encode() + b"\n")
        await process.stdin.drain()
        pids = await self._wait_for_pids(pid_file)
        release_file.write_text("exit\n", encoding="utf-8")
        await self._wait_for_exited_leader_with_live_descendants(pids)
        process.stdin.close()
        await process.stdin.wait_closed()
        self.assertEqual(await asyncio.wait_for(process.wait(), timeout=2), 0)
        stdout = await process.stdout.read()
        stderr = await process.stderr.read()
        self.assertEqual(stderr, b"")
        records = stdout.splitlines()
        self.assertEqual(len(records), 1)
        response = json.loads(records[0])
        self.assertEqual(response["id"], 120)
        self.assertEqual(response["error"]["code"], adapter.REQUEST_CANCELLED)
        for pid in pids:
            self.assertFalse(await self._wait_not_live(pid), f"stdio-EOF process survived: {pid}")
        self.assertFalse(runtime_owner_path.exists())

    async def test_anchored_runner_signal_order_grace_and_lost_anchor_rules(self):
        state = adapter._CallState(request_id="anchored-order")
        state.leader_status = -signal.SIGKILL
        events = []
        killed = False

        class FakeProcess:
            pid = 424242

            def wait(self):
                events.append(("wait", time.monotonic()))
                return -signal.SIGKILL

        runner = adapter._AnchoredBackendRunner(
            state=state,
            command=("unused",),
            cwd=self.runtime,
            environment=TEST_RUNTIME_ENVIRONMENT,
            timeout=1.0,
            stdout_limit=128,
            stderr_limit=128,
            terminate_grace=0.05,
            leader_poll_interval=0.01,
        )

        def kill_group(unused_pid, requested_signal):
            nonlocal killed
            events.append((requested_signal, time.monotonic()))
            if requested_signal == signal.SIGKILL:
                killed = True
            elif requested_signal == 0 and killed:
                raise ProcessLookupError

        started = time.monotonic()
        with mock.patch.object(adapter.os, "killpg", side_effect=kill_group):
            status = runner._terminate_and_reap(FakeProcess())
        elapsed = time.monotonic() - started
        self.assertEqual(status, -signal.SIGKILL)
        self.assertGreaterEqual(elapsed, runner.terminate_grace * 0.75)
        self.assertTrue(state.term_sent)
        self.assertTrue(state.kill_sent)
        self.assertEqual(sum(event[0] == "wait" for event in events), 1)
        wait_index = next(index for index, event in enumerate(events) if event[0] == "wait")
        self.assertLess(
            max(
                index
                for index, event in enumerate(events)
                if event[0] in (signal.SIGTERM, signal.SIGKILL)
            ),
            wait_index,
        )

        graceful_state = adapter._CallState(request_id="graceful")
        graceful_state.leader_status = 0
        graceful_process = mock.Mock(pid=424243)
        graceful_process.wait.return_value = 0
        graceful_runner = adapter._AnchoredBackendRunner(
            state=graceful_state,
            command=("unused",),
            cwd=self.runtime,
            environment=TEST_RUNTIME_ENVIRONMENT,
            timeout=1.0,
            stdout_limit=128,
            stderr_limit=128,
            terminate_grace=0.05,
            leader_poll_interval=0.01,
        )
        with mock.patch.object(
            adapter.os,
            "killpg",
            side_effect=(None, ProcessLookupError()),
        ) as graceful_kill_group:
            self.assertEqual(graceful_runner._terminate_and_reap(graceful_process), 0)
        self.assertEqual(
            [call.args[1] for call in graceful_kill_group.call_args_list],
            [signal.SIGTERM, 0],
        )
        self.assertFalse(graceful_state.kill_sent)
        graceful_process.wait.assert_called_once_with()

        lost_state = adapter._CallState(request_id="lost-anchor")
        lost_runner = adapter._AnchoredBackendRunner(
            state=lost_state,
            command=("unused",),
            cwd=self.runtime,
            environment=TEST_RUNTIME_ENVIRONMENT,
            timeout=1.0,
            stdout_limit=128,
            stderr_limit=128,
            terminate_grace=0.05,
            leader_poll_interval=0.01,
        )
        lost_process = types.SimpleNamespace(pid=424244)
        with (
            mock.patch.object(adapter.os, "waitid", side_effect=ChildProcessError),
            mock.patch.object(adapter.os, "killpg") as lost_kill_group,
            self.assertRaises(adapter.BackendFailure),
        ):
            lost_runner._signal_group(lost_process, signal.SIGTERM)
        lost_kill_group.assert_not_called()
        self.assertTrue(lost_state.anchor_lost)

        reap_lost_state = adapter._CallState(request_id="lost-during-reap")
        reap_lost_state.leader_status = 0
        reap_lost_process = mock.Mock(pid=424246)
        reap_lost_process.wait.side_effect = ChildProcessError
        reap_lost_runner = adapter._AnchoredBackendRunner(
            state=reap_lost_state,
            command=("unused",),
            cwd=self.runtime,
            environment=TEST_RUNTIME_ENVIRONMENT,
            timeout=1.0,
            stdout_limit=128,
            stderr_limit=128,
            terminate_grace=0.05,
            leader_poll_interval=0.01,
        )
        with (
            mock.patch.object(
                adapter.os,
                "killpg",
                side_effect=(None, ProcessLookupError()),
            ),
            self.assertRaises(adapter.BackendFailure),
        ):
            reap_lost_runner._terminate_and_reap(reap_lost_process)
        self.assertTrue(reap_lost_state.anchor_lost)

        setup_state = adapter._CallState(request_id="setup-failure")
        setup_runner = adapter._AnchoredBackendRunner(
            state=setup_state,
            command=("unused",),
            cwd=self.runtime,
            environment=TEST_RUNTIME_ENVIRONMENT,
            timeout=1.0,
            stdout_limit=128,
            stderr_limit=128,
            terminate_grace=0.05,
            leader_poll_interval=0.01,
        )
        setup_process = mock.Mock(pid=424247)

        def mark_reaped(unused_process):
            setup_state.leader_status = 0
            setup_state.reaped = True
            return 0

        with (
            mock.patch.object(adapter.subprocess, "Popen", return_value=setup_process),
            mock.patch.object(adapter.os, "pipe", side_effect=OSError("fixture")),
            mock.patch.object(
                setup_runner,
                "_terminate_and_reap",
                side_effect=mark_reaped,
            ) as setup_cleanup,
            self.assertRaises(adapter.BackendFailure),
        ):
            setup_runner.run()
        setup_cleanup.assert_called_once_with(setup_process)

        unavailable_state = adapter._CallState(request_id="unavailable")
        unavailable_state.leader_status = 0
        unavailable_runner = adapter._AnchoredBackendRunner(
            state=unavailable_state,
            command=("unused",),
            cwd=self.runtime,
            environment=TEST_RUNTIME_ENVIRONMENT,
            timeout=1.0,
            stdout_limit=128,
            stderr_limit=128,
            terminate_grace=0.05,
            leader_poll_interval=0.01,
        )
        with mock.patch.object(adapter.os, "killpg", side_effect=ProcessLookupError()):
            self.assertFalse(
                unavailable_runner._signal_group(
                    types.SimpleNamespace(pid=424245), signal.SIGTERM
                )
            )
        with (
            mock.patch.object(
                adapter.os, "killpg", side_effect=OSError(errno.EPERM, "not permitted")
            ),
            self.assertRaisesRegex(adapter.BackendFailure, "permission denied"),
        ):
            unavailable_runner._signal_group(
                types.SimpleNamespace(pid=424245), signal.SIGTERM
            )

        transient_state = adapter._CallState(request_id="transient-eperm")
        transient_runner = adapter._AnchoredBackendRunner(
            state=transient_state,
            command=("unused",),
            cwd=self.runtime,
            environment=TEST_RUNTIME_ENVIRONMENT,
            timeout=1.0,
            stdout_limit=128,
            stderr_limit=128,
            terminate_grace=0.05,
            leader_poll_interval=10.0,
        )
        transient_process = types.SimpleNamespace(pid=424251)
        with (
            mock.patch.object(
                transient_runner,
                "_peek_leader_anchor",
                side_effect=(None, 0, 0),
            ) as observe_anchor,
            mock.patch.object(
                adapter.os,
                "killpg",
                side_effect=OSError(errno.EPERM, "transient zombie transition"),
            ) as transient_kill_group,
            mock.patch.object(
                adapter,
                "_exited_group_has_only_zombie_members",
                side_effect=(False, True),
            ) as observe_transient_quiescence,
            mock.patch.object(adapter.time, "sleep") as transient_sleep,
        ):
            self.assertFalse(
                transient_runner._signal_group(transient_process, signal.SIGTERM)
            )
        self.assertEqual(observe_anchor.call_count, 3)
        transient_kill_group.assert_called_once_with(424251, signal.SIGTERM)
        self.assertEqual(observe_transient_quiescence.call_count, 2)
        observe_transient_quiescence.assert_has_calls(
            [mock.call(424251), mock.call(424251)]
        )
        transient_sleep.assert_called_once_with(0.01)

        persistent_state = adapter._CallState(request_id="persistent-eperm")
        persistent_runner = adapter._AnchoredBackendRunner(
            state=persistent_state,
            command=("unused",),
            cwd=self.runtime,
            environment=TEST_RUNTIME_ENVIRONMENT,
            timeout=1.0,
            stdout_limit=128,
            stderr_limit=128,
            terminate_grace=0.01,
            leader_poll_interval=0.005,
        )
        with (
            mock.patch.object(
                persistent_runner, "_peek_leader_anchor", return_value=0
            ),
            mock.patch.object(
                adapter.os,
                "killpg",
                side_effect=OSError(errno.EPERM, "persistent denial"),
            ),
            mock.patch.object(
                adapter,
                "_exited_group_has_only_zombie_members",
                return_value=False,
            ) as persistent_observer,
            self.assertRaisesRegex(adapter.BackendFailure, "permission denied"),
        ):
            persistent_runner._signal_group(
                types.SimpleNamespace(pid=424252), signal.SIGTERM
            )
        self.assertGreaterEqual(persistent_observer.call_count, 2)

        quiescent_state = adapter._CallState(request_id="quiescent")
        quiescent_state.leader_status = 0
        quiescent_runner = adapter._AnchoredBackendRunner(
            state=quiescent_state,
            command=("unused",),
            cwd=self.runtime,
            environment=TEST_RUNTIME_ENVIRONMENT,
            timeout=1.0,
            stdout_limit=128,
            stderr_limit=128,
            terminate_grace=0.05,
            leader_poll_interval=0.01,
        )
        with (
            mock.patch.object(
                adapter, "_exited_group_has_only_zombie_members", return_value=True
            ) as observe_quiescent,
            mock.patch.object(adapter.os, "killpg") as quiescent_kill_group,
        ):
            self.assertFalse(
                quiescent_runner._signal_group(
                    types.SimpleNamespace(pid=424248), signal.SIGTERM
                )
            )
        observe_quiescent.assert_called_once_with(424248)
        quiescent_kill_group.assert_not_called()

    async def test_process_group_observer_selector_failure_cleans_observer(self):
        observer = mock.Mock()
        observer.stdout = io.BytesIO()
        observer.poll.return_value = None
        observer.wait.return_value = -signal.SIGTERM
        with (
            mock.patch.object(adapter.subprocess, "Popen", return_value=observer),
            mock.patch.object(
                adapter.selectors,
                "DefaultSelector",
                side_effect=OSError("descriptor exhaustion"),
            ),
            self.assertRaisesRegex(adapter.BackendFailure, "observer setup"),
        ):
            adapter._exited_group_has_only_zombie_members(424249)

        observer.terminate.assert_called_once_with()
        observer.wait.assert_called_once_with(timeout=0.1)
        self.assertTrue(observer.stdout.closed)

    async def test_process_group_observer_accepts_leader_plus_only_zombie_members(self):
        self.assertTrue(
            adapter._group_observation_is_quiescent(
                b"424252 Z\n424253 Z+\n424254 Z\n", 424252
            )
        )
        self.assertTrue(hasattr(adapter, "_exited_group_has_only_zombie_members"))
        self.assertFalse(hasattr(adapter, "_exited_group_has_only_zombie_leader"))
        self.assertFalse(
            adapter._group_observation_is_quiescent(
                b"424252 Z\n424253 S\n", 424252
            )
        )
        self.assertFalse(
            adapter._group_observation_is_quiescent(b"424253 Z\n", 424252)
        )

    async def test_process_group_observer_cleanup_timeout_is_named(self):
        observer = mock.Mock()
        observer.stdout = io.BytesIO()
        observer.poll.return_value = None
        observer.wait.side_effect = (
            subprocess.TimeoutExpired(["ps"], 0.1),
            subprocess.TimeoutExpired(["ps"], 0.1),
        )
        with (
            mock.patch.object(adapter.subprocess, "Popen", return_value=observer),
            mock.patch.object(
                adapter.selectors,
                "DefaultSelector",
                side_effect=OSError("descriptor exhaustion"),
            ),
            self.assertRaisesRegex(adapter.BackendFailure, "did not exit"),
        ):
            adapter._exited_group_has_only_zombie_members(424251)

        observer.terminate.assert_called_once_with()
        observer.kill.assert_called_once_with()
        self.assertTrue(observer.stdout.closed)

    async def test_failed_quiescence_observer_cannot_prevent_backend_group_cleanup(self):
        state = adapter._CallState(request_id="observer-failure-cleanup")
        state.leader_status = 0
        process = mock.Mock(pid=424250)
        process.wait.return_value = 0
        runner = adapter._AnchoredBackendRunner(
            state=state,
            command=("unused",),
            cwd=self.runtime,
            environment=TEST_RUNTIME_ENVIRONMENT,
            timeout=1.0,
            stdout_limit=128,
            stderr_limit=128,
            terminate_grace=0.05,
            leader_poll_interval=0.01,
        )
        with (
            mock.patch.object(
                adapter,
                "_exited_group_has_only_zombie_members",
                side_effect=adapter.BackendFailure("observer unavailable"),
            ),
            mock.patch.object(
                adapter.os,
                "killpg",
                side_effect=(None, ProcessLookupError()),
            ) as kill_group,
        ):
            self.assertEqual(runner._terminate_and_reap(process), 0)

        self.assertEqual(
            kill_group.call_args_list,
            [mock.call(424250, signal.SIGTERM), mock.call(424250, 0)],
        )
        process.wait.assert_called_once_with()


class MCPAdapterProductionResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = (self.root / "runtime").resolve()
        hermes = self.runtime / "plugin/hermes"
        hermes.mkdir(parents=True)
        (hermes / "tools.json").write_bytes(RUNTIME_TOOLS.read_bytes())
        launcher = hermes / "jackal_hermes"
        launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        launcher.chmod(0o755)
        # These fixtures seed the snapshot with the REPO catalog rather than the
        # sealed release catalog the provisioner downloads, so the adapter's
        # expected count is locked to the repo surface here.  The module
        # constant itself stays pinned to that release (see RUNTIME_TOOL_COUNT)
        # and is repinned at seal time, not by a repo-side surface addition.
        count_patch = mock.patch.object(
            adapter, "EXPECTED_TOOL_COUNT", RUNTIME_TOOL_COUNT)
        count_patch.start()
        self.addCleanup(count_patch.stop)
        self.provisioner = types.SimpleNamespace(
            EPOCH="v1.7.0",
            ASSET="jackal-v1.7.0-macos-arm64.tar.gz",
            PACKAGE_SIZE=118862060,
            PACKAGE_SHA256="21c7ede586f30a58772f321f7dbb36ab66213e199785489f99133710ac56096e",
            SHA256SUMS_SHA256="f1f794ccd2ba331e6188840cfc089180cdcd744f23c1880f8364a81b230c1a28",
            SELFTEST_TIMEOUT=30.0,
            SELFTEST_OUTPUT_LIMIT=65536,
            effective_release_pins=lambda *a, **k: {
                "epoch": "v1.7.0",
                "asset": "jackal-v1.7.0-macos-arm64.tar.gz",
                "package_size": 118862060,
                "package_sha256":
                    "21c7ede586f30a58772f321f7dbb36ab66213e199785489f99133710ac56096e",
                "package_directory": "jackal-v1.7.0-macos-arm64",
                "sha256sums_sha256":
                    "f1f794ccd2ba331e6188840cfc089180cdcd744f23c1880f8364a81b230c1a28",
            },
            default_locator_path=lambda: self.root / "locator.json",
            validate_host=mock.Mock(return_value=None),
            reap_orphaned_runtime_snapshots=mock.Mock(return_value=()),
            runtime_subprocess_environment=mock.Mock(
                return_value=real_provisioner.runtime_subprocess_environment({})
            ),
        )
        package_metadata = {
            "schema": "jackal-runtime-package-v1",
            "epoch": self.provisioner.EPOCH,
            "asset": self.provisioner.ASSET,
            "package_size": self.provisioner.PACKAGE_SIZE,
            "package_sha256": self.provisioner.PACKAGE_SHA256,
        }
        (self.runtime / ".jackal-package.json").write_text(
            json.dumps(package_metadata, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        self.snapshot_owners = []

        def create_snapshot(unused_runtime, **unused_kwargs):
            snapshot_root = self.root / f"snapshot-{len(self.snapshot_owners)}"
            shutil.copytree(self.runtime, snapshot_root)
            snapshot_root.chmod(0o700)
            owner = types.SimpleNamespace(root=snapshot_root.resolve(), close=mock.Mock())
            self.snapshot_owners.append(owner)
            return owner

        self.provisioner.create_runtime_snapshot = mock.Mock(side_effect=create_snapshot)

    def _write_locator(self, path):
        document = {
            "schema": "jackal-codex-plugin-runtime-v1",
            "epoch": self.provisioner.EPOCH,
            "runtime_path": str(self.runtime),
            "package_size": self.provisioner.PACKAGE_SIZE,
            "package_sha256": self.provisioner.PACKAGE_SHA256,
        }
        path.write_text(
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    def test_resolver_accepts_only_absolute_env_or_strict_locator(self):
        self.assertEqual(
            adapter.resolve_runtime_path(
                environ={"JACKAL_HOME": str(self.runtime)},
                provisioner=self.provisioner,
            ),
            self.runtime,
        )
        with self.assertRaises(adapter.StartupError):
            adapter.resolve_runtime_path(
                environ={"JACKAL_HOME": "relative/runtime"},
                provisioner=self.provisioner,
            )

        locator = self.root / "locator.json"
        self._write_locator(locator)
        self.assertEqual(
            adapter.resolve_runtime_path(
                environ={}, locator_path=locator, provisioner=self.provisioner
            ),
            self.runtime,
        )
        locator.write_text(locator.read_text().replace('"epoch":"v1.7.0"', '"epoch":"v9"'))
        with self.assertRaises(adapter.StartupError):
            adapter.resolve_runtime_path(
                environ={}, locator_path=locator, provisioner=self.provisioner
            )

    def test_production_builder_verifies_plugin_and_runtime_with_wrapper_pins(self):
        plugin_root = self.root / "cache/jackel/0.1.0"
        (plugin_root / "mcp").mkdir(parents=True)
        (plugin_root / "mcp/server.py").write_text("# cache fixture\n")
        (plugin_root / "PLUGIN_IDENTITY.sha256").write_text("fixture\n")
        identity_verifier = mock.Mock(return_value=())
        runtime_validator = mock.Mock(return_value={})

        server = adapter.build_production_server(
            plugin_root=plugin_root,
            environ={"JACKAL_HOME": str(self.runtime)},
            provisioner=self.provisioner,
            identity_verifier=identity_verifier,
            runtime_validator=runtime_validator,
        )

        identity_verifier.assert_called_once_with(
            plugin_root, plugin_root / "PLUGIN_IDENTITY.sha256"
        )
        self.provisioner.validate_host.assert_called_once_with()
        self.provisioner.reap_orphaned_runtime_snapshots.assert_called_once_with()
        self.provisioner.runtime_subprocess_environment.assert_called_once_with(
            {"JACKAL_HOME": str(self.runtime)}
        )
        runtime_validator.assert_called_once_with(
            self.runtime,
            timeout=self.provisioner.SELFTEST_TIMEOUT,
            output_limit=self.provisioner.SELFTEST_OUTPUT_LIMIT,
            expected_tree_sha256=self.provisioner.SHA256SUMS_SHA256,
        )
        self.provisioner.create_runtime_snapshot.assert_called_once_with(
            self.runtime,
            timeout=self.provisioner.SELFTEST_TIMEOUT,
            output_limit=self.provisioner.SELFTEST_OUTPUT_LIMIT,
            expected_tree_sha256=self.provisioner.SHA256SUMS_SHA256,
        )
        self.assertEqual(len(server.tool_definitions), RUNTIME_TOOL_COUNT)
        self.assertNotEqual(server.runtime_root, self.runtime)
        self.assertEqual(server.runtime_root, self.snapshot_owners[0].root)
        self.assertEqual(
            server.launcher,
            self.snapshot_owners[0].root / "plugin/hermes/jackal_hermes",
        )
        asyncio.run(server.close())
        self.snapshot_owners[0].close.assert_called_once_with()

    def test_production_builder_passes_only_an_explicit_private_snapshot_parent(self):
        plugin_root = self.root / "private-parent-plugin"
        plugin_root.mkdir()
        (plugin_root / "PLUGIN_IDENTITY.sha256").write_text("fixture\n")
        private_parent = self.root / "private-tmpfs"

        server = adapter.build_production_server(
            plugin_root=plugin_root,
            environ={"JACKAL_HOME": str(self.runtime)},
            snapshot_parent=private_parent,
            provisioner=self.provisioner,
            identity_verifier=mock.Mock(return_value=()),
            runtime_validator=mock.Mock(return_value={}),
        )

        self.provisioner.create_runtime_snapshot.assert_called_once_with(
            self.runtime,
            timeout=self.provisioner.SELFTEST_TIMEOUT,
            output_limit=self.provisioner.SELFTEST_OUTPUT_LIMIT,
            expected_tree_sha256=self.provisioner.SHA256SUMS_SHA256,
            temporary_parent=os.fspath(private_parent),
        )
        asyncio.run(server.close())

    def test_production_builder_refuses_orphan_cleanup_failure_before_runtime_copy(self):
        plugin_root = self.root / "reaper-failure-plugin"
        plugin_root.mkdir()
        (plugin_root / "PLUGIN_IDENTITY.sha256").write_text("fixture\n")
        self.provisioner.reap_orphaned_runtime_snapshots.side_effect = OSError(
            "fixture cleanup failure"
        )
        runtime_validator = mock.Mock(return_value={})

        with self.assertRaisesRegex(adapter.StartupError, "orphaned runtime snapshot"):
            adapter.build_production_server(
                plugin_root=plugin_root,
                environ={"JACKAL_HOME": str(self.runtime)},
                provisioner=self.provisioner,
                identity_verifier=mock.Mock(return_value=()),
                runtime_validator=runtime_validator,
            )

        runtime_validator.assert_not_called()
        self.provisioner.create_runtime_snapshot.assert_not_called()

    def test_linux_namespace_wrapper_execs_mount_and_pid_isolation_after_probe(self):
        probe = mock.Mock(returncode=0)
        with (
            mock.patch.object(adapter.sys, "platform", "linux"),
            mock.patch.object(
                adapter,
                "_fixed_executable",
                side_effect=("/usr/bin/unshare", "/usr/bin/true"),
            ),
            mock.patch.object(
                adapter, "_mount_namespace_identity", return_value="mnt:[123]"
            ),
            mock.patch.object(adapter.subprocess, "run", return_value=probe) as run,
            mock.patch.object(adapter.os, "execv", side_effect=OSError("fixture")) as execv,
        ):
            self.assertFalse(adapter._exec_in_private_snapshot_namespace())

        probe_command = run.call_args.args[0]
        command = execv.call_args.args[1]
        self.assertEqual(probe_command[-1], "/usr/bin/true")
        self.assertIn("--mount", command)
        self.assertIn("--pid", command)
        self.assertIn("--fork", command)
        self.assertIn("--kill-child=SIGKILL", command)
        self.assertIn("--forward-signals", command)
        self.assertIn(adapter.PRIVATE_NAMESPACE_FLAG, command)

    def test_linux_namespace_probe_or_private_mount_failure_uses_exact_reaper_fallback(self):
        with (
            mock.patch.object(adapter.sys, "platform", "linux"),
            mock.patch.object(
                adapter,
                "_fixed_executable",
                side_effect=("/usr/bin/unshare", "/usr/bin/true"),
            ),
            mock.patch.object(
                adapter, "_mount_namespace_identity", return_value="mnt:[123]"
            ),
            mock.patch.object(
                adapter.subprocess, "run", return_value=mock.Mock(returncode=1)
            ),
            mock.patch.object(adapter.os, "execv") as execv,
        ):
            self.assertFalse(adapter._exec_in_private_snapshot_namespace())
        execv.assert_not_called()

        with (
            mock.patch.object(
                adapter.sys,
                "argv",
                [adapter.__file__, adapter.PRIVATE_NAMESPACE_FLAG, "mnt:[123]"],
            ),
            mock.patch.object(
                adapter,
                "_prepare_private_snapshot_parent",
                side_effect=adapter.StartupError("fixture mount refusal"),
            ),
            mock.patch.object(adapter, "_run_production_server", return_value=17) as run,
            mock.patch.object(adapter, "_exec_in_private_snapshot_namespace") as enter,
        ):
            self.assertEqual(adapter.main(), 17)
        run.assert_called_once_with(None)
        enter.assert_not_called()

    def test_private_namespace_child_arguments_are_exact(self):
        self.assertEqual(
            adapter._parse_namespace_child(
                [adapter.PRIVATE_NAMESPACE_FLAG, "mnt:[123]"]
            ),
            "mnt:[123]",
        )
        for arguments in (
            ["--other", "mnt:[123]"],
            [adapter.PRIVATE_NAMESPACE_FLAG, "forged"],
            [adapter.PRIVATE_NAMESPACE_FLAG, "mnt:[123]", "extra"],
        ):
            with self.subTest(arguments=arguments), self.assertRaises(adapter.StartupError):
                adapter._parse_namespace_child(arguments)

    def test_production_builder_refuses_unsupported_host_before_any_runtime_access(self):
        plugin_root = self.root / "host-guard-plugin"
        plugin_root.mkdir()
        (plugin_root / "PLUGIN_IDENTITY.sha256").write_text("fixture\n")
        cases = (("Linux", "arm64"), ("Darwin", "x86_64"), ("Unknown", "unknown"))
        for system, machine in cases:
            with (
                self.subTest(system=system, machine=machine),
                mock.patch.object(real_provisioner.platform, "system", return_value=system),
                mock.patch.object(real_provisioner.platform, "machine", return_value=machine),
                mock.patch.object(adapter, "resolve_runtime_path") as resolver,
                mock.patch.object(adapter, "_load_catalog") as catalog,
                mock.patch.object(real_provisioner, "validate_runtime") as validator,
                self.assertRaises(adapter.StartupError),
            ):
                adapter.build_production_server(
                    plugin_root=plugin_root,
                    environ={"JACKAL_HOME": str(self.runtime)},
                    provisioner=real_provisioner,
                    identity_verifier=mock.Mock(return_value=()),
                )
            resolver.assert_not_called()
            catalog.assert_not_called()
            validator.assert_not_called()

    def test_production_bootstraps_all_wrapper_modules_from_pinned_bytes(self):
        plugin_root = self.root / "verified-wrapper-plugin"
        plugin_root.mkdir()
        (plugin_root / "PLUGIN_IDENTITY.sha256").write_text("fixture\n")
        inventory = {
            "mcp/advanced.py": "d" * 64,
            "mcp/certificates/hellgate_v1.json.zlib": "f" * 64,
            "mcp/engineering.py": "3" * 64,
            "mcp/hellgate_verify.py": "e" * 64,
            "mcp/measurement.py": "c" * 64,
            "mcp/numbertheory.py": "2" * 64,
            "mcp/stem.py": "1" * 64,
            "scripts/provision_runtime.py": "a" * 64,
            "scripts/verify_plugin.py": "b" * 64,
        }
        records = tuple(
            types.SimpleNamespace(path=path, digest=digest)
            for path, digest in sorted(inventory.items())
        )
        verifier_module = types.SimpleNamespace(
            verify_manifest=mock.Mock(return_value=records)
        )
        runtime_validator = mock.Mock(return_value={})
        checker_module = types.SimpleNamespace(
            VerificationRefusal=type("FixtureRefusal", (Exception,), {}),
            verify_bytes=mock.Mock(
                return_value={
                    "status": "bounded",
                    "checker_verdict": "ACCEPT",
                    "formal": False,
                    "fields": {
                        "trial_diagnostics": {
                            "schema": "jackal-hellgate-trial-diagnostics-v1",
                            "status": "bounded",
                            "subject": "normalized-certificate-trial-phi",
                            "non_claims": ["not the exact ground state u0"],
                        },
                        "ground_state_transfer": {
                            "schema": "jackal-hellgate-ground-transfer-v1",
                            "status": "bounded",
                            "subject": "positive-normalized-ground-state-u0",
                            "method": "lambda-strong-convexity-density-transfer-v1",
                            "non_claims": ["does not enclose polynomial moments"],
                        },
                    },
                }
            ),
        )

        with (
            mock.patch.object(adapter, "_read_identity_inventory", return_value=inventory),
            mock.patch.object(
                adapter, "_load_verified_module",
                side_effect=(
                    verifier_module,
                    measurement,
                    advanced,
                    checker_module,
                    stem,
                    numbertheory,
                    engineering,
                    self.provisioner,
                ),
            ) as loader,
            mock.patch.object(
                adapter,
                "_read_verified_plugin_blob",
                return_value=(b"compressed-fixture", "f" * 64),
            ),
            mock.patch.object(
                adapter, "_decompress_certificate", return_value=b"certificate-fixture"
            ),
        ):
            server = adapter.build_production_server(
                plugin_root=plugin_root,
                environ={"JACKAL_HOME": str(self.runtime)},
                runtime_validator=runtime_validator,
            )

        self.assertEqual(
            loader.call_args_list,
            [
                mock.call(
                    plugin_root, "scripts/verify_plugin.py",
                    "jackel_codex_verify_plugin", inventory,
                ),
                mock.call(
                    plugin_root, "mcp/measurement.py",
                    "jackel_codex_measurement", inventory,
                ),
                mock.call(
                    plugin_root, "mcp/advanced.py",
                    "jackel_codex_advanced", inventory,
                ),
                mock.call(
                    plugin_root, "mcp/hellgate_verify.py",
                    "jackel_codex_hellgate_verify", inventory,
                ),
                mock.call(
                    plugin_root, "mcp/stem.py",
                    "jackel_codex_stem", inventory,
                ),
                mock.call(
                    plugin_root, "mcp/numbertheory.py",
                    "jackel_codex_numbertheory", inventory,
                ),
                mock.call(
                    plugin_root, "mcp/engineering.py",
                    "jackel_codex_engineering", inventory,
                ),
                mock.call(
                    plugin_root, "scripts/provision_runtime.py",
                    "jackel_codex_provision_runtime", inventory,
                ),
            ],
        )
        verifier_module.verify_manifest.assert_called_once_with(
            plugin_root, plugin_root / "PLUGIN_IDENTITY.sha256"
        )
        self.assertEqual(
            len(server.tool_definitions),
            RUNTIME_TOOL_COUNT
            + adapter.EXPECTED_MEASUREMENT_TOOL_COUNT
            + adapter.EXPECTED_ADVANCED_TOOL_COUNT
            + adapter.EXPECTED_STEM_TOOL_COUNT
            + adapter.EXPECTED_NUMBER_THEORY_TOOL_COUNT
            + adapter.EXPECTED_ENGINEERING_TOOL_COUNT,
        )
        asyncio.run(server.close())

    def test_snapshot_is_cleaned_when_post_copy_startup_refuses(self):
        plugin_root = self.root / "startup-cleanup-plugin"
        plugin_root.mkdir()
        (plugin_root / "PLUGIN_IDENTITY.sha256").write_text("fixture\n")
        with (
            mock.patch.object(adapter, "_load_catalog", side_effect=adapter.StartupError("fixture")),
            self.assertRaises(adapter.StartupError),
        ):
            adapter.build_production_server(
                plugin_root=plugin_root,
                environ={"JACKAL_HOME": str(self.runtime)},
                provisioner=self.provisioner,
                identity_verifier=mock.Mock(return_value=()),
                runtime_validator=mock.Mock(return_value={}),
            )
        self.snapshot_owners[0].close.assert_called_once_with()

    def test_startup_snapshot_cleanup_failure_is_reported_not_suppressed(self):
        plugin_root = self.root / "startup-cleanup-failure-plugin"
        plugin_root.mkdir()
        (plugin_root / "PLUGIN_IDENTITY.sha256").write_text("fixture\n")
        create_snapshot = self.provisioner.create_runtime_snapshot.side_effect

        def create_uncleanable_snapshot(*args, **kwargs):
            owner = create_snapshot(*args, **kwargs)
            owner.close.side_effect = OSError("fixture cleanup failure")
            return owner

        self.provisioner.create_runtime_snapshot.side_effect = create_uncleanable_snapshot
        with (
            mock.patch.object(
                adapter, "_load_catalog", side_effect=adapter.StartupError("fixture")
            ),
            self.assertRaisesRegex(adapter.StartupError, "snapshot cleanup failed"),
        ):
            adapter.build_production_server(
                plugin_root=plugin_root,
                environ={"JACKAL_HOME": str(self.runtime)},
                provisioner=self.provisioner,
                identity_verifier=mock.Mock(return_value=()),
                runtime_validator=mock.Mock(return_value={}),
            )
        self.snapshot_owners[0].close.assert_called_once_with()

    def test_calls_remain_bound_to_snapshot_after_original_launcher_backend_and_aba_mutation(self):
        source = self.root / "bound-runtime"
        hermes = source / "plugin/hermes"
        hermes.mkdir(parents=True)
        tools = RUNTIME_TOOLS.read_bytes()
        launcher_bytes = (
            b"#!/bin/sh\n"
            b"if [ \"$1\" = selftest ]; then echo plugin_hermes.identity_match=true; exit 0; fi\n"
            b"exec ./plugin/hermes/backend.sh \"$@\"\n"
        )
        backend_bytes = (
            b"#!/bin/sh\n"
            b"IFS= read -r request\n"
            b"echo '{\"jsonrpc\":\"2.0\",\"id\":\"jackal-adapter-backend\","
            b"\"result\":{\"status\":\"checked\",\"origin\":\"snapshot\"}}'\n"
        )
        files = {
            "MANIFEST.sha256": b"fixture manifest\n",
            "plugin/hermes/backend.sh": backend_bytes,
            "plugin/hermes/jackal_hermes": launcher_bytes,
            "plugin/hermes/tools.json": tools,
        }
        checksums = "".join(
            f"{hashlib.sha256(data).hexdigest()}  ./{path}\n"
            for path, data in sorted(files.items())
        ).encode()
        files["SHA256SUMS"] = checksums
        for relative, data in files.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        launcher = hermes / "jackal_hermes"
        backend = hermes / "backend.sh"
        launcher.chmod(0o755)
        backend.chmod(0o755)
        package_metadata = {
            "schema": "jackal-runtime-package-v1",
            "epoch": "v1.7.0",
            "asset": "fixture.tar.gz",
            "package_size": 123,
            "package_sha256": "c" * 64,
        }
        (source / ".jackal-package.json").write_text(
            json.dumps(package_metadata, sort_keys=True, separators=(",", ":")) + "\n"
        )
        fixture_provisioner = types.SimpleNamespace(
            EPOCH="v1.7.0", ASSET="fixture.tar.gz", PACKAGE_SIZE=123,
            PACKAGE_SHA256="c" * 64,
            SHA256SUMS_SHA256=hashlib.sha256(checksums).hexdigest(),
            effective_release_pins=lambda *a, **k: {
                "epoch": "v1.7.0", "asset": "fixture.tar.gz",
                "package_size": 123, "package_sha256": "c" * 64,
                "package_directory": "fixture",
                "sha256sums_sha256": hashlib.sha256(checksums).hexdigest(),
            },
            SELFTEST_TIMEOUT=2.0, SELFTEST_OUTPUT_LIMIT=65536,
            validate_host=mock.Mock(return_value=None),
            reap_orphaned_runtime_snapshots=real_provisioner.reap_orphaned_runtime_snapshots,
            validate_runtime=real_provisioner.validate_runtime,
            create_runtime_snapshot=real_provisioner.create_runtime_snapshot,
            runtime_subprocess_environment=real_provisioner.runtime_subprocess_environment,
            default_locator_path=lambda: self.root / "unused-locator",
        )

        server = adapter.build_production_server(
            plugin_root=(self.root / "bound-plugin"),
            environ={"JACKAL_HOME": str(source.resolve())},
            provisioner=fixture_provisioner,
            identity_verifier=mock.Mock(return_value=()),
        )
        snapshot_root = server.runtime_root
        self.assertNotEqual(snapshot_root, source)
        self.assertEqual(snapshot_root.stat().st_mode & 0o777, 0o700)

        saved_launcher = self.root / "saved-launcher"
        saved_backend = self.root / "saved-backend"
        os.link(launcher, saved_launcher)
        os.link(backend, saved_backend)
        for path, forged in (
            (launcher, b"#!/bin/sh\necho forged-launcher\n"),
            (backend, b"#!/bin/sh\necho '{\"status\":\"checked\",\"origin\":\"forged\"}'\n"),
        ):
            path.unlink()
            path.write_bytes(forged)
            path.chmod(0o755)
        for path, saved in ((launcher, saved_launcher), (backend, saved_backend)):
            path.unlink()
            os.link(saved, path)
        launcher.write_bytes(b"#!/bin/sh\necho forged-after-aba\n")
        backend.write_bytes(
            b"#!/bin/sh\necho '{\"status\":\"checked\",\"origin\":\"forged-after-aba\"}'\n"
        )
        launcher.chmod(0o755)
        backend.chmod(0o755)

        response = asyncio.run(server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "jackal_exact", "arguments": {"expression": "1+1"}},
        }))
        self.assertEqual(
            response["result"]["structuredContent"],
            {"status": "checked", "origin": "snapshot"},
        )
        asyncio.run(server.close())
        self.assertFalse(snapshot_root.exists())


if __name__ == "__main__":
    unittest.main()
