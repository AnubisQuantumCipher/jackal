import ast
import copy
import hashlib
import unittest
from fractions import Fraction

from plugins.jackel.mcp import server as adapter
from plugins.jackel.mcp import stem


FIXTURE_IDENTITY = "d" * 64


class ExactFixtureKernel:
    """Small test double: product code still has to delegate every numeric field."""

    def __init__(self):
        self.calls = []

    def __call__(self, name, arguments):
        self.calls.append((name, copy.deepcopy(arguments)))
        if name == "jackal_exact":
            expression = arguments["expression"]
            value = self._fraction(ast.parse(expression.replace("^", "**"), mode="eval").body)
            rendered = str(value.numerator)
            if value.denominator != 1:
                rendered += f"/{value.denominator}"
            return {
                "status": "exact",
                "fields": {"parsed": expression, "exact": rendered},
                "formal": False,
            }
        if name == "jackal_evaluate":
            return {"status": "estimated", "engine_output": "0", "formal": False}
        if name == "jackal_integrate_adaptive":
            return {
                "status": "estimated",
                "fields": {"integral": "1/4", "parsed": arguments["expression"]},
                "formal": False,
            }
        if name in {"jackal_sqrt_rat_bound", "jackal_ln_rat_bound"}:
            return {
                "status": "formal-bounded",
                "checker_rerun": "ACCEPT",
                "fields": {
                    "parsed": arguments["expression"],
                    "input_lo": arguments["input_lo"],
                    "input_hi": arguments["input_hi"],
                },
                "formal": True,
            }
        if name == "jackal_canon":
            return {"status": "exact", "engine_output": "(pow x 2)", "formal": False}
        if name == "jackal_diff":
            return {"status": "checked", "engine_output": "2*x", "formal": False}
        raise AssertionError(f"unexpected delegated tool: {name}")

    def _fraction(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return Fraction(node.value)
        if isinstance(node, ast.UnaryOp):
            value = self._fraction(node.operand)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
        if isinstance(node, ast.BinOp):
            left = self._fraction(node.left)
            right = self._fraction(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow) and right.denominator == 1:
                return left ** right.numerator
        raise AssertionError(f"unsupported fixture expression: {ast.dump(node)}")


class StemSurfaceTests(unittest.TestCase):
    def test_definitions_form_one_closed_identity_pinned_surface(self):
        definitions = adapter.build_stem_tool_definitions(stem)

        self.assertEqual(
            {definition["name"] for definition in definitions}, adapter.STEM_TOOL_NAMES
        )
        self.assertEqual(len(definitions), adapter.EXPECTED_STEM_TOOL_COUNT)
        for definition in definitions:
            with self.subTest(tool=definition["name"]):
                self.assertIs(definition["inputSchema"]["additionalProperties"], False)
                self.assertEqual(
                    definition["annotations"],
                    {
                        "readOnlyHint": True,
                        "destructiveHint": False,
                        "idempotentHint": True,
                        "openWorldHint": False,
                    },
                )

    def test_definition_tampering_refuses_before_merge(self):
        original = stem.tool_definitions
        definitions = original()
        definitions[0] = copy.deepcopy(definitions[0])
        definitions[0]["name"] = "jackal_forged"
        stem.tool_definitions = lambda: definitions
        try:
            with self.assertRaises(adapter.CatalogError):
                adapter.build_stem_tool_definitions(stem)
        finally:
            stem.tool_definitions = original

    def test_matrix_inverse_and_all_numeric_cells_delegate(self):
        kernel = ExactFixtureKernel()
        body = stem.dispatch_integrated(
            "jackal_matrix",
            {"operation": "inverse", "matrix": [["1", "2"], ["3", "5"]]},
            kernel,
            FIXTURE_IDENTITY,
        )

        self.assertEqual(body["status"], "exact")
        self.assertEqual(body["fields"]["matrix"], [["-5", "2"], ["3", "-1"]])
        self.assertTrue(kernel.calls)
        self.assertEqual({name for name, unused in kernel.calls}, {"jackal_exact"})
        self.assertTrue(any("NOT formal-bounded" in item for item in body["non_claims"]))

    def test_every_matrix_route_and_singular_refusal(self):
        kernel = ExactFixtureKernel()
        cases = (
            (
                {"operation": "add", "matrix": [["1", "2"], ["3", "4"]], "second_matrix": [["5", "6"], ["7", "8"]]},
                "matrix",
                [["6", "8"], ["10", "12"]],
            ),
            (
                {"operation": "multiply", "matrix": [["1", "2"], ["3", "4"]], "second_matrix": [["5", "6"], ["7", "8"]]},
                "matrix",
                [["19", "22"], ["43", "50"]],
            ),
            (
                {"operation": "transpose", "matrix": [["1", "2", "3"], ["4", "5", "6"]]},
                "matrix",
                [["1", "4"], ["2", "5"], ["3", "6"]],
            ),
            (
                {"operation": "determinant", "matrix": [["1", "2"], ["3", "4"]]},
                "determinant",
                "-2",
            ),
            (
                {"operation": "rref", "matrix": [["1", "2"], ["2", "4"]]},
                "matrix",
                [["1", "2"], ["0", "0"]],
            ),
            (
                {"operation": "solve", "matrix": [["1", "0"], ["0", "1"]], "vector": ["7", "9"]},
                "solution",
                ["7", "9"],
            ),
        )
        for arguments, field, expected in cases:
            with self.subTest(operation=arguments["operation"]):
                body = stem.dispatch_integrated(
                    "jackal_matrix", arguments, kernel, FIXTURE_IDENTITY
                )
                self.assertEqual(body["status"], "exact")
                self.assertEqual(body["fields"][field], expected)

        singular = stem.dispatch_integrated(
            "jackal_matrix",
            {"operation": "inverse", "matrix": [["1", "2"], ["2", "4"]]},
            kernel,
            FIXTURE_IDENTITY,
        )
        self.assertEqual(singular["status"], "refused")
        self.assertEqual(singular["reason"], "matrix-singular")

    def test_polynomial_regression_keeps_model_status_separate_from_exact_fields(self):
        kernel = ExactFixtureKernel()
        body = stem.dispatch_integrated(
            "jackal_regression",
            {
                "model": "polynomial_ols",
                "degree": "1",
                "x": ["0", "1", "2"],
                "y": ["1", "3", "5"],
            },
            kernel,
            FIXTURE_IDENTITY,
        )

        self.assertEqual(body["status"], "model-based")
        self.assertEqual(body["fields"]["coefficients_ascending"], ["1", "2"])
        self.assertEqual(body["fields"]["sse"], "0")
        self.assertEqual(body["field_status"]["coefficients_ascending"], "exact")
        self.assertTrue(any("do not establish" in item for item in body["non_claims"]))

    def test_probability_and_hypothesis_preserve_model_assumptions(self):
        kernel = ExactFixtureKernel()
        probability = stem.dispatch_integrated(
            "jackal_probability",
            {"operation": "binomial_cdf", "n": "3", "k": "1", "p": "1/2"},
            kernel,
            FIXTURE_IDENTITY,
        )
        hypothesis = stem.dispatch_integrated(
            "jackal_hypothesis",
            {
                "operation": "exact_binomial_tail",
                "alternative": "greater",
                "n": "3",
                "k": "2",
                "p0": "1/2",
            },
            kernel,
            FIXTURE_IDENTITY,
        )

        self.assertEqual(probability["status"], "model-based")
        self.assertEqual(probability["fields"]["probability"], "1/2")
        self.assertEqual(hypothesis["status"], "model-based")
        self.assertEqual(hypothesis["fields"]["p_value"], "1/2")
        self.assertEqual(hypothesis["consequence_ceiling"], "advisory")

    def test_binomial_endpoint_probabilities_do_not_divide_by_zero(self):
        kernel = ExactFixtureKernel()
        cases = (
            ({"operation": "binomial_cdf", "n": "3", "k": "1", "p": "1"}, "0"),
            ({"operation": "binomial_pmf", "n": "3", "k": "3", "p": "1"}, "1"),
            ({"operation": "binomial_cdf", "n": "3", "k": "0", "p": "0"}, "1"),
        )
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                body = stem.dispatch_integrated(
                    "jackal_probability", arguments, kernel, FIXTURE_IDENTITY
                )
                self.assertEqual(body["status"], "model-based")
                self.assertEqual(body["fields"]["probability"], expected)

    def test_normal_probability_and_all_z_alternatives_use_estimated_finite_tails(self):
        kernel = ExactFixtureKernel()
        normal = stem.dispatch_integrated(
            "jackal_probability",
            {
                "operation": "normal_cdf",
                "z": "0",
                "tail_cutoff": "6",
                "tolerance": "1/10",
            },
            kernel,
            FIXTURE_IDENTITY,
        )
        self.assertEqual(normal["status"], "model-based")
        self.assertEqual(normal["field_status"]["finite_cutoff_cdf_estimate"], "estimated")

        for alternative in ("less", "greater", "two_sided"):
            with self.subTest(alternative=alternative):
                body = stem.dispatch_integrated(
                    "jackal_hypothesis",
                    {
                        "operation": "one_sample_z",
                        "alternative": alternative,
                        "sample_mean": "1",
                        "null_mean": "1",
                        "population_sd": "2",
                        "n": "4",
                        "tail_cutoff": "6",
                        "tolerance": "1/10",
                    },
                    kernel,
                    FIXTURE_IDENTITY,
                )
                self.assertEqual(body["status"], "model-based")
                self.assertEqual(body["field_status"]["p_value_estimate"], "estimated")

    def test_sensor_provenance_stays_supplied_and_stddev_stays_formal_bounded(self):
        kernel = ExactFixtureKernel()
        body = stem.dispatch_integrated(
            "jackal_sensor",
            {
                "operation": "linear_calibration",
                "sensor_id": "imu-1",
                "channel": "accel-x",
                "quantity": "acceleration",
                "unit": "m/s2",
                "samples": ["1", "2", "3"],
                "source": "fixture-export.csv",
                "observed_at": "fixture-time",
                "scale": "2",
                "offset": "1",
                "calibration_source": "fixture-sheet",
                "calibration_as_of": "fixture-date",
            },
            kernel,
            FIXTURE_IDENTITY,
        )

        self.assertEqual(body["status"], "exact-given")
        self.assertEqual(body["given"]["input_provenance"], "supplied")
        self.assertIs(body["given"]["calibration"]["verified"], False)
        self.assertEqual(
            body["field_status"]["population_stddev_enclosure"], "formal-bounded"
        )
        self.assertTrue(any("does not claim it opened" in item for item in body["non_claims"]))

    def test_aerospace_formal_scalar_does_not_upgrade_physical_model(self):
        kernel = ExactFixtureKernel()
        body = stem.dispatch_integrated(
            "jackal_aerospace",
            {"operation": "vis_viva", "parameters": {"mu": "10", "radius": "2", "semi_major_axis": "3"}},
            kernel,
            FIXTURE_IDENTITY,
        )

        self.assertEqual(body["status"], "model-based")
        self.assertEqual(body["field_status"]["speed_enclosure"], "formal-bounded")
        self.assertEqual(body["consequence_ceiling"], "advisory")
        self.assertTrue(any("physical model" in item for item in body["non_claims"]))

    def test_every_aerospace_model_route_preserves_advisory_model_status(self):
        kernel = ExactFixtureKernel()
        cases = (
            {"operation": "circular_orbit", "parameters": {"mu": "10", "radius": "2"}},
            {"operation": "rocket_equation", "parameters": {"exhaust_velocity": "3", "initial_mass": "5", "final_mass": "2"}},
            {"operation": "hohmann_transfer", "parameters": {"mu": "10", "r1": "2", "r2": "3"}},
            {"operation": "plane_change", "parameters": {"velocity": "7", "angle_degrees": "30"}},
        )
        for arguments in cases:
            with self.subTest(operation=arguments["operation"]):
                body = stem.dispatch_integrated(
                    "jackal_aerospace", arguments, kernel, FIXTURE_IDENTITY
                )
                self.assertEqual(body["status"], "model-based")
                self.assertEqual(body["consequence_ceiling"], "advisory")
                self.assertTrue(body["assumptions"])

        invalid_angle = stem.dispatch_integrated(
            "jackal_aerospace",
            {"operation": "plane_change", "parameters": {"velocity": "7", "angle_degrees": "181"}},
            kernel,
            FIXTURE_IDENTITY,
        )
        self.assertEqual(invalid_angle["status"], "refused")
        self.assertEqual(invalid_angle["reason"], "domain")

    def test_linked_workspace_embeds_digest_bound_html_without_upgrading_results(self):
        kernel = ExactFixtureKernel()
        body = stem.dispatch_integrated(
            "jackal_linked_workspace",
            {"expression": "x^2", "x_min": "-1", "x_max": "1", "samples": "17"},
            kernel,
            FIXTURE_IDENTITY,
        )

        self.assertEqual(body["status"], "checked")
        resource = body["_mcp_content"][1]["resource"]
        digest = hashlib.sha256(resource["text"].encode("utf-8")).hexdigest()
        self.assertEqual(resource["uri"], f"ui://jackal/linked-workspace/{digest}")
        self.assertIn("Pixels are not proof", resource["text"])
        wrapped = adapter.backend_result(body)
        self.assertEqual(wrapped["content"][1]["type"], "resource")
        self.assertNotIn("_mcp_content", wrapped["structuredContent"])

    def test_malformed_numeric_token_and_kernel_refusal_fail_closed(self):
        calls = []
        malformed = stem.dispatch_integrated(
            "jackal_matrix",
            {"operation": "transpose", "matrix": [["1junk"]]},
            lambda name, arguments: calls.append((name, arguments)),
            FIXTURE_IDENTITY,
        )
        refused = stem.dispatch_integrated(
            "jackal_matrix",
            {"operation": "determinant", "matrix": [["1"]]},
            lambda unused_name, unused_arguments: {
                "status": "refused",
                "reason": "fixture-refusal",
                "detail": "fixture detail",
            },
            FIXTURE_IDENTITY,
        )

        self.assertEqual(malformed["status"], "refused")
        self.assertEqual(malformed["reason"], "args")
        self.assertEqual(calls, [])
        self.assertEqual(refused["status"], "refused")
        self.assertEqual(refused["reason"], "kernel-refused:fixture-refusal")

    def test_delegated_status_tampering_cannot_upgrade_a_field(self):
        kernel = ExactFixtureKernel()

        def tampered(name, arguments):
            if name == "jackal_sqrt_rat_bound":
                return {
                    "status": "estimated",
                    "checker_rerun": "ACCEPT",
                    "formal": False,
                }
            return kernel(name, arguments)

        body = stem.dispatch_integrated(
            "jackal_sensor",
            {
                "operation": "ingest_batch",
                "sensor_id": "fixture",
                "channel": "x",
                "quantity": "q",
                "unit": "u",
                "samples": ["1", "2"],
                "source": "fixture",
                "observed_at": "fixture",
            },
            tampered,
            FIXTURE_IDENTITY,
        )

        self.assertEqual(body["status"], "refused")
        self.assertEqual(body["reason"], "kernel-error")
        self.assertNotIn("field_status", body)

    def test_adaptive_integration_status_tampering_refuses(self):
        kernel = ExactFixtureKernel()

        def tampered(name, arguments):
            if name == "jackal_integrate_adaptive":
                return {
                    "status": "checked",
                    "fields": {"integral": "1/2"},
                    "formal": False,
                }
            return kernel(name, arguments)

        body = stem.dispatch_integrated(
            "jackal_probability",
            {
                "operation": "normal_cdf",
                "z": "0",
                "tail_cutoff": "6",
                "tolerance": "1/10",
            },
            tampered,
            FIXTURE_IDENTITY,
        )

        self.assertEqual(body["status"], "refused")
        self.assertEqual(body["reason"], "kernel-error")


class StemResourceValidationTests(unittest.TestCase):
    def test_resource_digest_or_uri_tampering_fails_closed(self):
        content = [
            {"type": "text", "text": "fixture"},
            {
                "type": "resource",
                "resource": {
                    "uri": "ui://jackal/linked-workspace/" + ("0" * 64),
                    "mimeType": "text/html",
                    "text": "<!doctype html><title>tampered</title>",
                },
            },
        ]
        with self.assertRaises(adapter.BackendFailure):
            adapter.backend_result({"status": "checked", "_mcp_content": content})


class StemResourceProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = adapter.MCPServer(
            runtime_root="/tmp",
            launcher="/bin/false",
            tool_definitions=adapter.build_stem_tool_definitions(stem),
            runtime_environment={"PATH": "/usr/bin:/bin"},
            stem_module=stem,
            stem_identity=FIXTURE_IDENTITY,
        )

    async def asyncTearDown(self):
        await self.server.close()

    async def test_resource_listing_and_shell_read_are_closed_to_one_uri(self):
        listed = await self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "list",
                "method": "resources/list",
                "params": {},
            }
        )
        resource = listed["result"]["resources"][0]
        self.assertEqual(resource["uri"], adapter.LINKED_WORKSPACE_SHELL_URI)

        read = await self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "read",
                "method": "resources/read",
                "params": {"uri": adapter.LINKED_WORKSPACE_SHELL_URI},
            }
        )
        contents = read["result"]["contents"][0]
        self.assertEqual(contents["mimeType"], "text/html")
        self.assertIn("Call jackal_linked_workspace", contents["text"])

        refused = await self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "refuse",
                "method": "resources/read",
                "params": {"uri": "file:///tmp/forbidden"},
            }
        )
        self.assertEqual(refused["error"]["code"], adapter.INVALID_PARAMS)


if __name__ == "__main__":
    unittest.main()
