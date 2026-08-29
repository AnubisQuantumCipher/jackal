import base64
import copy
import struct
import unittest
from fractions import Fraction

from plugins.jackel.mcp import advanced
from plugins.jackel.mcp import server as adapter


FIXTURE_IDENTITY = "a" * 64


class AdvancedSurfaceTests(unittest.TestCase):
    def test_definitions_form_one_strict_identity_pinned_surface(self):
        definitions = adapter.build_advanced_tool_definitions(advanced)

        self.assertEqual(
            {definition["name"] for definition in definitions},
            adapter.ADVANCED_TOOL_NAMES,
        )
        self.assertEqual(len(definitions), adapter.EXPECTED_ADVANCED_TOOL_COUNT)
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
        original = advanced.tool_definitions
        definitions = original()
        definitions[0] = copy.deepcopy(definitions[0])
        definitions[0]["name"] = "jackal_forged"
        advanced.tool_definitions = lambda: definitions
        try:
            with self.assertRaises(adapter.CatalogError):
                adapter.build_advanced_tool_definitions(advanced)
        finally:
            advanced.tool_definitions = original

    def test_cas_preserves_the_delegated_status_and_body(self):
        delegated = {
            "status": "exact",
            "formal": False,
            "fields": {"parsed": "1/3+1/3", "exact": "2/3"},
            "non_claims": ["fixture residual"],
        }
        calls = []

        def kernel_call(name, arguments):
            calls.append((name, copy.deepcopy(arguments)))
            return copy.deepcopy(delegated)

        body = advanced.dispatch_integrated(
            "jackal_cas",
            {"operation": "exact", "arguments": {"expression": "1/3+1/3"}},
            kernel_call,
            FIXTURE_IDENTITY,
        )

        self.assertEqual(body["status"], "exact")
        self.assertEqual(body["result"], delegated)
        self.assertEqual(
            calls,
            [("jackal_exact", {"expression": "1/3+1/3"})],
        )
        self.assertIn("adds no assurance", body["non_claims"][0])

    def test_cas_refusal_is_not_routed_to_a_weaker_lane(self):
        def kernel_call(name, arguments):
            return {
                "status": "refused",
                "reason": "fixture-refusal",
                "detail": "unsupported fixture",
            }

        body = advanced.dispatch_integrated(
            "jackal_cas",
            {"operation": "exact", "arguments": {"expression": "sqrt(2)"}},
            kernel_call,
            FIXTURE_IDENTITY,
        )

        self.assertEqual(body["status"], "refused")
        self.assertEqual(body["reason"], "kernel-refused:fixture-refusal")
        self.assertIn("no weaker lane", body["non_claims"][0].lower())

    def test_graph_delegates_coordinates_and_values_and_emits_png(self):
        coordinate_index = 0
        calls = []

        def kernel_call(name, arguments):
            nonlocal coordinate_index
            calls.append((name, copy.deepcopy(arguments)))
            if name == "jackal_exact":
                coordinate = Fraction(-1) + Fraction(coordinate_index, 8)
                coordinate_index += 1
                return {
                    "status": "exact",
                    "fields": {
                        "parsed": arguments["expression"],
                        "exact": str(coordinate),
                    },
                }
            if name == "jackal_evaluate":
                return {"status": "estimated", "engine_output": "0"}
            self.fail(f"unexpected kernel call: {name}")

        body = advanced.dispatch_integrated(
            "jackal_graph",
            {"expression": "x^2", "x_min": "-1", "x_max": "1", "samples": "17"},
            kernel_call,
            FIXTURE_IDENTITY,
        )

        self.assertEqual(body["status"], "estimated")
        self.assertIs(body["formal"], False)
        self.assertEqual(body["fields"]["finite_sample_count"], 17)
        self.assertEqual(len([name for name, unused in calls if name == "jackal_exact"]), 17)
        self.assertEqual(len([name for name, unused in calls if name == "jackal_evaluate"]), 17)
        image = body["_mcp_content"][1]
        self.assertEqual(image["mimeType"], "image/png")
        png = base64.b64decode(image["data"], validate=True)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(
            struct.unpack(">II", png[16:24]),
            (advanced.GRAPH_WIDTH, advanced.GRAPH_HEIGHT),
        )
        self.assertTrue(any("visualization only" in item for item in body["non_claims"]))

    def test_graph_breaks_at_a_refused_sample(self):
        coordinate_index = 0
        evaluation_index = 0

        def kernel_call(name, arguments):
            nonlocal coordinate_index, evaluation_index
            if name == "jackal_exact":
                coordinate = Fraction(-1) + Fraction(coordinate_index, 8)
                coordinate_index += 1
                return {"status": "exact", "fields": {"exact": str(coordinate)}}
            evaluation_index += 1
            if evaluation_index == 9:
                return {
                    "status": "refused",
                    "reason": "domain",
                    "detail": "fixture gap",
                }
            return {"status": "estimated", "engine_output": str(evaluation_index)}

        body = advanced.dispatch_integrated(
            "jackal_graph",
            {"expression": "1/x", "x_min": "-1", "x_max": "1", "samples": "17"},
            kernel_call,
            FIXTURE_IDENTITY,
        )

        refused = [point for point in body["fields"]["points"] if point["status"] == "refused"]
        self.assertEqual(len(refused), 1)
        self.assertTrue(any("break" in item for item in body["non_claims"]))

    def test_hellgate_result_requires_startup_configuration_and_exact_problem_id(self):
        result = {
            "status": "bounded",
            "checker_verdict": "ACCEPT",
            "formal": False,
            "fields": {
                "eigenvalue_decimal_interval": ["-5", "-4"],
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
        advanced.configure_hellgate(
            result,
            advanced_sha256="a" * 64,
            checker_sha256="b" * 64,
            certificate_sha256="c" * 64,
        )
        body = advanced.dispatch_integrated(
            "jackal_hellgate_ground_state",
            {"problem_id": "hellgate-v1"},
            lambda unused_name, unused_arguments: self.fail("certificate replay delegates nothing"),
            FIXTURE_IDENTITY,
        )
        self.assertEqual(body["status"], "bounded")
        self.assertIs(body["formal"], False)
        self.assertEqual(body["identities"]["hellgate_checker_sha256"], "b" * 64)

        refusal = advanced.dispatch_integrated(
            "jackal_hellgate_ground_state",
            {"problem_id": "different-problem"},
            lambda unused_name, unused_arguments: {},
            FIXTURE_IDENTITY,
        )
        self.assertEqual(refusal["status"], "refused")
        self.assertEqual(refusal["reason"], "unsupported-problem")


class AdvancedMCPContentTests(unittest.TestCase):
    def test_reserved_content_is_validated_and_removed_from_structured_result(self):
        png = b"\x89PNG\r\n\x1a\nfixture"
        backend = {
            "status": "estimated",
            "_mcp_content": [
                {"type": "text", "text": "fixture graph"},
                {
                    "type": "image",
                    "data": base64.b64encode(png).decode("ascii"),
                    "mimeType": "image/png",
                },
            ],
        }

        result = adapter.backend_result(backend)

        self.assertNotIn("_mcp_content", result["structuredContent"])
        self.assertEqual(result["content"][0]["text"], "fixture graph")
        self.assertEqual(result["content"][1]["mimeType"], "image/png")
        self.assertIn("_mcp_content", backend)

    def test_malformed_content_injection_fails_closed(self):
        cases = (
            [{"type": "image", "data": "not-base64", "mimeType": "image/png"}],
            [{"type": "image", "data": base64.b64encode(b"GIF89a").decode("ascii"), "mimeType": "image/png"}],
            [{"type": "resource", "uri": "file:///tmp/forbidden"}],
        )
        for content in cases:
            with self.subTest(content=content), self.assertRaises(adapter.BackendFailure):
                adapter.backend_result({"status": "estimated", "_mcp_content": content})


if __name__ == "__main__":
    unittest.main()
