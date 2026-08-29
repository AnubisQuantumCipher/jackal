import copy
import unittest

from plugins.jackel.mcp import measurement
from plugins.jackel.mcp import server as adapter


FIXTURE_IDENTITY = "a" * 64


class MeasurementSurfaceTests(unittest.TestCase):
    def test_identity_pinned_definitions_are_one_closed_surface(self):
        definitions = adapter.build_measurement_tool_definitions(measurement)

        self.assertEqual(
            {definition["name"] for definition in definitions},
            adapter.MEASUREMENT_TOOL_NAMES,
        )
        self.assertEqual(len(definitions), adapter.EXPECTED_MEASUREMENT_TOOL_COUNT)
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
        original = measurement.tool_definitions
        definitions = original()
        definitions[0] = copy.deepcopy(definitions[0])
        definitions[0]["name"] = "jackal_forged"
        measurement.tool_definitions = lambda: definitions
        try:
            with self.assertRaises(adapter.CatalogError):
                adapter.build_measurement_tool_definitions(measurement)
        finally:
            measurement.tool_definitions = original

    def test_scientific_notation_is_not_split(self):
        text = (
            "Bounds: 10^-12, 10**-12, 10^{-12}, 10⁻¹², 2e-12, "
            "and 1×10⁻¹²."
        )

        def no_kernel_call(unused_name, unused_arguments):
            self.fail("the lexical scan must not call the arithmetic runtime")

        body = measurement.dispatch_integrated(
            "jackal_scan",
            {"text": text, "context_window": 60},
            no_kernel_call,
            FIXTURE_IDENTITY,
        )

        self.assertEqual(body["status"], "checked")
        self.assertEqual(
            [item["text"] for item in body["fields"]["numerals"]],
            ["10^-12", "10**-12", "10^{-12}", "10⁻¹²", "2e-12", "1×10⁻¹²"],
        )
        self.assertEqual(
            body["identities"]["jackal_measurement_sha256"], FIXTURE_IDENTITY
        )

    def test_integer_variance_uses_canonical_point_interval(self):
        exact_values = {
            "(0) + (4) + (6) + (2)": "12",
            "(12) / 4": "3",
            "((2) + (4)) / 2": "3",
            "((0) - (3))^2 + ((4) - (3))^2 + ((6) - (3))^2 + ((2) - (3))^2": "20",
            "(20) / 4": "5",
            "(6) - (0)": "6",
            "(20) / 3": "20/3",
            "2": "2",
            "3": "3",
        }
        calls = []

        def kernel_call(name, arguments):
            calls.append((name, copy.deepcopy(arguments)))
            if name == "jackal_exact":
                expression = arguments["expression"]
                value = exact_values[expression]
                return {
                    "status": "exact",
                    "fields": {"parsed": expression, "exact": value, "approx": value},
                    "identities": {"evaluator_sha256": "b" * 64},
                }
            if name == "jackal_sqrt_rat_bound":
                self.assertEqual(arguments["input_lo"], "5")
                self.assertEqual(arguments["input_hi"], "5")
                return {
                    "status": "formal-bounded",
                    "checker_rerun": "ACCEPT",
                    "checker_output": "output 2 3",
                }
            self.fail(f"unexpected delegated tool {name}")

        body = measurement.dispatch_integrated(
            "jackal_stat",
            {"sample": [0, 4, 6, 2], "include_stddev": True},
            kernel_call,
            FIXTURE_IDENTITY,
        )

        self.assertEqual(body["status"], "exact")
        self.assertEqual(body["fields"]["population_variance"], "5")
        self.assertEqual(
            body["fields"]["field_status"]["population_stddev_enclosure"],
            "formal-bounded",
        )
        sqrt_calls = [arguments for name, arguments in calls if name == "jackal_sqrt_rat_bound"]
        self.assertEqual(sqrt_calls, [{"expression": "sqrt(x)", "input_lo": "5", "input_hi": "5"}])
        self.assertNotIn("5/1", repr(calls))

    def test_kernel_refusal_propagates_without_fallback(self):
        calls = []

        def kernel_call(name, arguments):
            calls.append((name, arguments))
            return {
                "status": "refused",
                "reason": "fixture-refusal",
                "detail": "fixture detail",
            }

        body = measurement.dispatch_integrated(
            "jackal_percent",
            {"op": "of", "a": "10", "b": "20"},
            kernel_call,
            FIXTURE_IDENTITY,
        )

        self.assertEqual(body["status"], "refused")
        self.assertEqual(body["reason"], "kernel-refused:fixture-refusal")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("fields", body)

    def test_json_float_sample_refuses_before_kernel_call(self):
        calls = []
        body = measurement.dispatch_integrated(
            "jackal_stat",
            {"sample": [0.1]},
            lambda name, arguments: calls.append((name, arguments)),
            FIXTURE_IDENTITY,
        )

        self.assertEqual(body["status"], "refused")
        self.assertEqual(body["reason"], "args")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
