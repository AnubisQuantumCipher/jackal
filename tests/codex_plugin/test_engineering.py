import ast
import copy
import math
import re
import unittest
from fractions import Fraction

import sympy

from plugins.jackel.mcp import engineering
from plugins.jackel.mcp import server as adapter


FIXTURE_IDENTITY = "f" * 64

_DECIMAL = re.compile(
    r"(?<![0-9A-Za-z_.])"
    r"([0-9]+)\.([0-9]+)[eE]([+-]?[0-9]+)"
    r"|(?<![0-9A-Za-z_.])([0-9]+)[eE]([+-]?[0-9]+)"
    r"|(?<![0-9A-Za-z_.])([0-9]+)\.([0-9]+)"
)


def _defloat(expression: str) -> str:
    """Rewrite decimal/scientific literals into exact integer ratios."""

    def replace(match: re.Match) -> str:
        if match.group(1) is not None:
            whole, frac, exp = match.group(1), match.group(2), int(match.group(3))
            mantissa = int(whole + frac)
            shift = exp - len(frac)
        elif match.group(4) is not None:
            mantissa = int(match.group(4))
            shift = int(match.group(5))
        else:
            whole, frac = match.group(6), match.group(7)
            mantissa = int(whole + frac)
            shift = -len(frac)
        if shift >= 0:
            return f"({mantissa}*10**{shift})"
        return f"({mantissa}/10**{-shift})"

    return _DECIMAL.sub(replace, expression)


def _render(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _fraction_eval(expression: str) -> Fraction:
    tree = ast.parse(_defloat(expression.replace("^", "**")), mode="eval").body

    def walk(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return Fraction(node.value)
        if isinstance(node, ast.UnaryOp):
            value = walk(node.operand)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
        if isinstance(node, ast.BinOp):
            left = walk(node.left)
            right = walk(node.right)
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

    return walk(tree)


def _sympy_poly(expression: str):
    x = sympy.Symbol("x")
    return sympy.Poly(sympy.sympify(_defloat(expression.replace("^", "**"))), x)


def _coeff_strings(poly) -> list[str]:
    return [_render(Fraction(str(c))) for c in reversed(poly.all_coeffs())]


class ExactFixtureKernel:
    """Test double for the sealed runtime; module code must delegate every claim."""

    def __init__(self):
        self.calls = []

    def __call__(self, name, arguments):
        self.calls.append((name, copy.deepcopy(arguments)))
        if name == "jackal_exact":
            value = _fraction_eval(arguments["expression"])
            return {
                "status": "exact",
                "fields": {"parsed": arguments["expression"], "exact": _render(value)},
                "formal": False,
            }
        if name == "jackal_poly_canon":
            poly = _sympy_poly(arguments["expression"])
            if poly.is_zero:
                return {
                    "status": "exact",
                    "fields": {"degree": "-1", "coeffs": "0", "exact_cert": "{}"},
                    "formal": False,
                }
            coeffs = _coeff_strings(poly)
            return {
                "status": "exact",
                "fields": {
                    "degree": str(poly.degree()),
                    "coeffs": ",".join(coeffs),
                    "exact_cert": '{"kind":"poly-canon"}',
                },
                "formal": False,
            }
        if name == "jackal_poly_gcd":
            lhs = _sympy_poly(arguments["lhs"])
            rhs = _sympy_poly(arguments["rhs"])
            gcd = lhs.gcd(rhs)
            return {
                "status": "exact",
                "fields": {
                    "gcd": ",".join(_coeff_strings(gcd.monic())),
                    "exact_cert": '{"kind":"poly-gcd"}',
                },
                "formal": False,
            }
        if name == "jackal_roots_isolate":
            poly = _sympy_poly(arguments["expression"])
            squarefree = poly.div(poly.gcd(poly.diff()))[0]
            intervals = squarefree.intervals()
            rendered = []
            for (low, high), _count in intervals:
                rendered.append(
                    f"[{_render(Fraction(str(low)))},{_render(Fraction(str(high)))}]"
                )
            return {
                "status": "exact",
                "fields": {
                    "distinct-real-roots": str(len(intervals)),
                    "intervals": "".join(rendered),
                    "exact_cert": '{"kind":"roots-isolate"}',
                },
                "formal": False,
            }
        if name in {"jackal_sqrt_rat_bound", "jackal_ln_rat_bound", "jackal_atan_rat_bound"}:
            value = _fraction_eval(arguments["input_lo"])
            if name == "jackal_sqrt_rat_bound":
                approx = math.sqrt(value)
            elif name == "jackal_ln_rat_bound":
                approx = math.log(value)
            else:
                approx = math.atan(value)
            center = Fraction(approx).limit_denominator(10**12)
            margin = Fraction(1, 10**6)
            return {
                "status": "formal-bounded",
                "checker_rerun": "ACCEPT",
                "receipt": {
                    "result": {
                        "enclosure_lo": _render(center - margin),
                        "enclosure_hi": _render(center + margin),
                    }
                },
                "formal": True,
            }
        raise AssertionError(f"unexpected delegated tool: {name}")


def dispatch(name, arguments, kernel=None):
    kernel = kernel or ExactFixtureKernel()
    result = engineering.dispatch_integrated(
        name, arguments, kernel, FIXTURE_IDENTITY
    )
    return result, kernel


class EngineeringSurfaceTests(unittest.TestCase):
    def test_definitions_form_one_closed_identity_pinned_surface(self):
        definitions = adapter.build_engineering_tool_definitions(engineering)
        self.assertEqual(
            {definition["name"] for definition in definitions},
            adapter.ENGINEERING_TOOL_NAMES,
        )
        self.assertEqual(len(definitions), adapter.EXPECTED_ENGINEERING_TOOL_COUNT)
        for definition in definitions:
            with self.subTest(tool=definition["name"]):
                self.assertIs(definition["inputSchema"]["additionalProperties"], False)

    def test_definition_tampering_refuses_before_merge(self):
        original = engineering.tool_definitions
        definitions = original()
        definitions[0] = copy.deepcopy(definitions[0])
        definitions[0]["name"] = "jackal_forged"
        engineering.tool_definitions = lambda: definitions
        try:
            with self.assertRaises(adapter.CatalogError):
                adapter.build_engineering_tool_definitions(engineering)
        finally:
            engineering.tool_definitions = original

    def test_unknown_tool_refuses(self):
        result, _ = dispatch("jackal_forged", {})
        self.assertEqual(result["reason"], "tool-unknown")

    def test_kernel_names_are_disjoint_from_runtime_delegates(self):
        self.assertFalse(
            adapter.ENGINEERING_TOOL_NAMES & adapter.ENGINEERING_KERNEL_TOOLS
        )


class ComplexTests(unittest.TestCase):
    def test_multiply_divide_round_trip(self):
        result, _ = dispatch(
            "jackal_complex",
            {"operation": "multiply", "a_re": "3", "a_im": "4", "b_re": "1", "b_im": "-2"},
        )
        self.assertEqual((result["fields"]["re"], result["fields"]["im"]), ("11", "-2"))
        result, _ = dispatch(
            "jackal_complex",
            {"operation": "divide", "a_re": "11", "a_im": "-2", "b_re": "1", "b_im": "-2"},
        )
        self.assertEqual((result["fields"]["re"], result["fields"]["im"]), ("3", "4"))

    def test_modulus_is_exact_square_plus_formal_enclosure(self):
        result, _ = dispatch(
            "jackal_complex", {"operation": "modulus", "a_re": "3", "a_im": "4"}
        )
        fields = result["fields"]
        self.assertEqual(fields["modulus_squared"], "25")
        enclosure = fields["modulus_enclosure"]
        self.assertEqual(enclosure["status"], "formal-bounded")
        self.assertEqual(result["field_status"]["modulus_enclosure"], "formal-bounded")
        result, _ = dispatch(
            "jackal_complex", {"operation": "modulus", "a_re": "0", "a_im": "0"}
        )
        self.assertEqual(result["fields"]["modulus"], "0")

    def test_power_square_and_multiply(self):
        result, _ = dispatch(
            "jackal_complex",
            {"operation": "power", "a_re": "1", "a_im": "1", "exponent": "4"},
        )
        self.assertEqual((result["fields"]["re"], result["fields"]["im"]), ("-4", "0"))
        result, _ = dispatch(
            "jackal_complex",
            {"operation": "power", "a_re": "2", "a_im": "-1", "exponent": "0"},
        )
        self.assertEqual((result["fields"]["re"], result["fields"]["im"]), ("1", "0"))

    def test_division_by_zero_refuses(self):
        result, _ = dispatch(
            "jackal_complex",
            {"operation": "divide", "a_re": "1", "a_im": "1", "b_re": "0", "b_im": "0"},
        )
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "domain")


class PolySolveTests(unittest.TestCase):
    def test_mixed_rational_and_irrational_roots(self):
        result, _ = dispatch("jackal_poly_solve", {"expression": "(x^2-2)*(x-3)"})
        fields = result["fields"]
        self.assertEqual(fields["degree"], "3")
        self.assertEqual(fields["distinct_real_roots"], "3")
        self.assertEqual(
            [root["root"] for root in fields["rational_roots"]], ["3"]
        )
        self.assertEqual(fields["rational_root_search"], "complete")
        self.assertEqual(fields["irrational_real_roots"], "2")
        self.assertEqual(fields["squarefree"], "true")
        self.assertEqual(fields["nonreal_root_count"], "0")

    def test_fractional_rational_roots(self):
        result, _ = dispatch("jackal_poly_solve", {"expression": "9*x^2-4"})
        roots = sorted(root["root"] for root in result["fields"]["rational_roots"])
        self.assertEqual(roots, ["-2/3", "2/3"])
        self.assertEqual(result["fields"]["irrational_real_roots"], "0")

    def test_nonreal_count_on_squarefree_polynomial(self):
        result, _ = dispatch("jackal_poly_solve", {"expression": "(x^2+1)*(x-1)"})
        fields = result["fields"]
        self.assertEqual(fields["distinct_real_roots"], "1")
        self.assertEqual(fields["nonreal_root_count"], "2")

    def test_repeated_roots_are_detected_and_not_overclaimed(self):
        result, _ = dispatch("jackal_poly_solve", {"expression": "(x-1)^2"})
        fields = result["fields"]
        self.assertEqual(fields["squarefree"], "false")
        self.assertEqual(fields["distinct_real_roots"], "1")
        self.assertNotIn("nonreal_root_count", fields)
        self.assertEqual([r["root"] for r in fields["rational_roots"]], ["1"])

    def test_zero_root_and_constant_and_zero_polynomial(self):
        result, _ = dispatch("jackal_poly_solve", {"expression": "x^3-x^2"})
        roots = sorted(root["root"] for root in result["fields"]["rational_roots"])
        self.assertEqual(roots, ["0", "1"])
        result, _ = dispatch("jackal_poly_solve", {"expression": "7"})
        self.assertEqual(result["fields"]["verdict"], "no-roots")
        result, _ = dispatch("jackal_poly_solve", {"expression": "x-x"})
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "poly-zero")

    def test_every_rational_root_evaluates_to_kernel_zero(self):
        result, _ = dispatch("jackal_poly_solve", {"expression": "6*x^2-5*x+1"})
        for root in result["fields"]["rational_roots"]:
            self.assertEqual(root["value_check"], "0")
        self.assertEqual(
            sorted(root["root"] for root in result["fields"]["rational_roots"]),
            ["1/2", "1/3"],
        )


class RouthTests(unittest.TestCase):
    def _oracle_rhp(self, expression: str) -> int:
        x = sympy.Symbol("x")
        roots = sympy.Poly(
            sympy.sympify(expression.replace("^", "**")), x
        ).all_roots()
        return sum(1 for root in roots if sympy.re(root) > 0)

    def test_stable_polynomial(self):
        expression = "x^3+6*x^2+11*x+6"
        result, _ = dispatch("jackal_routh_stability", {"expression": expression})
        fields = result["fields"]
        self.assertEqual(fields["verdict"], "stable")
        self.assertEqual(fields["sign_changes"], "0")
        self.assertEqual(int(fields["right_half_plane_roots"]), self._oracle_rhp(expression))

    def test_unstable_polynomial_counts_rhp_roots(self):
        expression = "x^3+4*x^2+x-6"
        result, _ = dispatch("jackal_routh_stability", {"expression": expression})
        fields = result["fields"]
        self.assertEqual(fields["verdict"], "unstable")
        self.assertEqual(int(fields["right_half_plane_roots"]), self._oracle_rhp(expression))

    def test_two_rhp_roots(self):
        # (x^2 - x + 1)(x + 2) has a complex pair with positive real part.
        expression = "x^3+x^2-x+2"
        result, _ = dispatch("jackal_routh_stability", {"expression": expression})
        self.assertEqual(int(result["fields"]["right_half_plane_roots"]), self._oracle_rhp(expression))

    def test_marginal_case_refuses(self):
        result, _ = dispatch("jackal_routh_stability", {"expression": "x^2+1"})
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "routh-singular")

    def test_degree_zero_refuses(self):
        result, _ = dispatch("jackal_routh_stability", {"expression": "5"})
        self.assertEqual(result["reason"], "routh-degree")


class CircuitTests(unittest.TestCase):
    def test_series_and_parallel_resistance(self):
        result, _ = dispatch(
            "jackal_circuit", {"operation": "series_resistance", "values": ["10", "5", "1/2"]}
        )
        self.assertEqual(result["fields"]["resistance"], "31/2")
        result, _ = dispatch(
            "jackal_circuit", {"operation": "parallel_resistance", "values": ["6", "3"]}
        )
        self.assertEqual(result["fields"]["resistance"], "2")
        self.assertEqual(result["status"], "model-based")
        self.assertEqual(result["consequence_ceiling"], "advisory")

    def test_voltage_divider_and_time_constants(self):
        result, _ = dispatch(
            "jackal_circuit",
            {"operation": "voltage_divider", "v_in": "12", "r1": "3", "r2": "1"},
        )
        self.assertEqual(result["fields"]["v_out"], "3")
        result, _ = dispatch(
            "jackal_circuit",
            {"operation": "rc_time_constant", "resistance": "1000", "capacitance": "1/1000000"},
        )
        self.assertEqual(result["fields"]["time_constant"], "1/1000")

    def test_resonant_omega_and_rlc_impedance(self):
        result, _ = dispatch(
            "jackal_circuit",
            {"operation": "resonant_omega", "inductance": "1/1000", "capacitance": "1/1000"},
        )
        self.assertEqual(result["fields"]["omega_squared"], "1000000")
        self.assertEqual(
            result["field_status"]["omega_enclosure"], "formal-bounded"
        )
        result, _ = dispatch(
            "jackal_circuit",
            {
                "operation": "rlc_series_impedance",
                "resistance": "3",
                "inductance": "2",
                "capacitance": "1/8",
                "omega": "2",
            },
        )
        fields = result["fields"]
        self.assertEqual(fields["reactance"], "0")
        self.assertEqual(fields["impedance_magnitude_squared"], "9")
        self.assertEqual(fields["phase_tangent"], "0")
        self.assertEqual(
            result["field_status"]["phase_enclosure_radians"], "formal-bounded"
        )

    def test_power_requires_exactly_two_inputs(self):
        result, _ = dispatch(
            "jackal_circuit", {"operation": "power", "voltage": "10", "current": "2"}
        )
        self.assertEqual(result["fields"]["power"], "20")
        result, _ = dispatch(
            "jackal_circuit",
            {"operation": "power", "voltage": "10", "current": "2", "resistance": "5"},
        )
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "args")

    def test_nonpositive_components_refuse(self):
        result, _ = dispatch(
            "jackal_circuit", {"operation": "parallel_resistance", "values": ["6", "0"]}
        )
        self.assertEqual(result["reason"], "domain")


class BeamTests(unittest.TestCase):
    def test_cantilever_end_load_matches_closed_form(self):
        result, _ = dispatch(
            "jackal_beam",
            {
                "operation": "cantilever_end_load",
                "length": "3",
                "elastic_modulus": "5",
                "second_moment": "7",
                "point_load": "2",
            },
        )
        fields = result["fields"]
        self.assertEqual(fields["max_deflection"], _render(Fraction(2 * 27, 3 * 35)))
        self.assertEqual(fields["max_moment"], "6")
        self.assertEqual(fields["support_reaction"], "2")
        self.assertEqual(result["status"], "model-based")
        self.assertEqual(result["consequence_ceiling"], "advisory")
        self.assertTrue(result["assumptions"])

    def test_simply_supported_udl_matches_closed_form(self):
        result, _ = dispatch(
            "jackal_beam",
            {
                "operation": "simply_supported_udl",
                "length": "2",
                "elastic_modulus": "10",
                "second_moment": "1/5",
                "distributed_load": "6",
            },
        )
        fields = result["fields"]
        self.assertEqual(
            fields["max_deflection"],
            _render(Fraction(5 * 6 * 16, 384 * 2)),
        )
        self.assertEqual(fields["max_moment"], "3")
        self.assertEqual(fields["support_reaction"], "6")

    def test_nonpositive_geometry_refuses(self):
        result, _ = dispatch(
            "jackal_beam",
            {
                "operation": "cantilever_udl",
                "length": "0",
                "elastic_modulus": "1",
                "second_moment": "1",
                "distributed_load": "1",
            },
        )
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "domain")


class ChemTests(unittest.TestCase):
    def test_molar_mass_water_and_nested_formula(self):
        result, _ = dispatch("jackal_chem", {"operation": "molar_mass", "formula": "H2O"})
        expected = 2 * Fraction("1.008") + Fraction("15.999")
        self.assertEqual(result["fields"]["molar_mass_g_per_mol"], _render(expected))
        result, _ = dispatch(
            "jackal_chem", {"operation": "molar_mass", "formula": "Ca(OH)2"}
        )
        expected = (
            Fraction("40.078") + 2 * (Fraction("15.999") + Fraction("1.008"))
        )
        self.assertEqual(result["fields"]["molar_mass_g_per_mol"], _render(expected))
        composition = {
            row["element"]: row["count"] for row in result["fields"]["composition"]
        }
        self.assertEqual(composition, {"Ca": "1", "H": "2", "O": "2"})

    def test_unknown_element_and_malformed_formula_refuse(self):
        result, _ = dispatch("jackal_chem", {"operation": "molar_mass", "formula": "Xx2"})
        self.assertEqual(result["reason"], "chem-element-unknown")
        result, _ = dispatch("jackal_chem", {"operation": "molar_mass", "formula": "H2O)"})
        self.assertEqual(result["reason"], "chem-formula")
        result, _ = dispatch("jackal_chem", {"operation": "molar_mass", "formula": "2H"})
        self.assertEqual(result["reason"], "chem-formula")

    def test_ideal_gas_solves_pressure_with_exact_r(self):
        result, _ = dispatch(
            "jackal_chem",
            {
                "operation": "ideal_gas",
                "solve_for": "pressure",
                "volume": "1/40",
                "moles": "1",
                "temperature": "300",
            },
        )
        gas_constant = Fraction("1.380649e-23") * Fraction("6.02214076e23")
        self.assertEqual(
            result["fields"]["gas_constant_J_per_mol_K"], _render(gas_constant)
        )
        expected = gas_constant * 300 / Fraction(1, 40)
        self.assertEqual(result["fields"]["pressure"], _render(expected))
        result, _ = dispatch(
            "jackal_chem",
            {
                "operation": "ideal_gas",
                "solve_for": "pressure",
                "pressure": "1",
                "volume": "1",
                "moles": "1",
                "temperature": "1",
            },
        )
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "args")

    def test_dilution_solves_the_missing_quantity(self):
        result, _ = dispatch(
            "jackal_chem",
            {"operation": "dilution", "c1": "2", "v1": "1/10", "v2": "1/2"},
        )
        self.assertEqual(result["fields"]["c2"], "2/5")
        result, _ = dispatch(
            "jackal_chem",
            {"operation": "dilution", "c1": "2", "v1": "1/10", "c2": "1/2", "v2": "1"},
        )
        self.assertEqual(result["status"], "refused")

    def test_ph_enclosure_brackets_the_true_value(self):
        result, _ = dispatch(
            "jackal_chem",
            {"operation": "ph_enclosure", "h_concentration": "1/10000000"},
        )
        fields = result["fields"]
        lo = Fraction(fields["ph_enclosure_lo"])
        hi = Fraction(fields["ph_enclosure_hi"])
        self.assertLessEqual(lo, 7)
        self.assertLessEqual(7, hi)
        self.assertEqual(result["field_status"]["ph_enclosure_lo"], "bounded")
        self.assertEqual(result["field_status"]["ln_h_enclosure"], "formal-bounded")

    def test_basic_solution_ph_interval_order_holds(self):
        result, _ = dispatch(
            "jackal_chem", {"operation": "ph_enclosure", "h_concentration": "10"}
        )
        lo = Fraction(result["fields"]["ph_enclosure_lo"])
        hi = Fraction(result["fields"]["ph_enclosure_hi"])
        self.assertLessEqual(lo, -1)
        self.assertLessEqual(-1, hi)


class DelegationDisciplineTests(unittest.TestCase):
    def test_every_result_names_delegation_and_identity(self):
        cases = [
            ("jackal_complex", {"operation": "modulus", "a_re": "3", "a_im": "4"}),
            ("jackal_poly_solve", {"expression": "x^2-2"}),
            ("jackal_routh_stability", {"expression": "x^2+3*x+2"}),
            ("jackal_circuit", {"operation": "series_resistance", "values": ["1", "2"]}),
            (
                "jackal_beam",
                {
                    "operation": "simply_supported_center_load",
                    "length": "4",
                    "elastic_modulus": "2",
                    "second_moment": "3",
                    "point_load": "5",
                },
            ),
            ("jackal_chem", {"operation": "molar_mass", "formula": "CO2"}),
        ]
        for name, arguments in cases:
            with self.subTest(tool=name):
                result, kernel = dispatch(name, arguments)
                self.assertIn(result["status"], {"exact", "model-based"})
                self.assertIs(result["formal"], False)
                self.assertEqual(
                    result["identities"],
                    {"jackal_engineering_sha256": FIXTURE_IDENTITY},
                )
                self.assertTrue(kernel.calls, "no delegation happened")
                self.assertEqual(len(result["delegated_to"]), len(kernel.calls))
                self.assertTrue(result["non_claims"])

    def test_kernel_refusal_propagates_without_substitution(self):
        class RefusingKernel(ExactFixtureKernel):
            def __call__(self, name, arguments):
                if name == "jackal_roots_isolate":
                    return {
                        "status": "refused",
                        "reason": "poly-budget",
                        "detail": "fixture refusal",
                    }
                return super().__call__(name, arguments)

        result, _ = dispatch(
            "jackal_poly_solve", {"expression": "x^2-2"}, RefusingKernel()
        )
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "kernel-refused:poly-budget")

    def test_kernel_error_fails_closed(self):
        class BrokenKernel(ExactFixtureKernel):
            def __call__(self, name, arguments):
                return "not-an-object"

        result, _ = dispatch(
            "jackal_complex", {"operation": "modulus", "a_re": "1", "a_im": "1"},
            BrokenKernel(),
        )
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "kernel-error")


class MCPServerValidationTests(unittest.TestCase):
    def _definitions(self):
        return [
            copy.deepcopy(definition)
            for definition in adapter.build_engineering_tool_definitions(engineering)
        ]

    def test_identity_without_module_is_rejected(self):
        with self.assertRaises(ValueError):
            adapter.MCPServer(
                runtime_root=".",
                launcher="/bin/false",
                tool_definitions=[],
                runtime_environment={"PATH": "/usr/bin"},
                engineering_identity=FIXTURE_IDENTITY,
            )

    def test_definitions_without_dispatcher_are_rejected(self):
        with self.assertRaises(ValueError):
            adapter.MCPServer(
                runtime_root=".",
                launcher="/bin/false",
                tool_definitions=self._definitions(),
                runtime_environment={"PATH": "/usr/bin"},
            )

    def test_module_with_valid_surface_is_accepted(self):
        server = adapter.MCPServer(
            runtime_root=".",
            launcher="/bin/false",
            tool_definitions=self._definitions(),
            runtime_environment={"PATH": "/usr/bin"},
            engineering_module=engineering,
            engineering_identity=FIXTURE_IDENTITY,
        )
        self.assertEqual(
            server._engineering_tools, adapter.ENGINEERING_TOOL_NAMES
        )


if __name__ == "__main__":
    unittest.main()
