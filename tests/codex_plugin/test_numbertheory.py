import ast
import copy
import math
import unittest
from fractions import Fraction

from plugins.jackel.mcp import numbertheory
from plugins.jackel.mcp import server as adapter


FIXTURE_IDENTITY = "e" * 64


def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    small = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)
    for p in small:
        if n % p == 0:
            return n == p
    d = n - 1
    r = 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for a in small:
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = (x * x) % n
            if x == n - 1:
                break
        else:
            return False
    return True


class ExactFixtureKernel:
    """Test double for the sealed runtime: the module must delegate every claim."""

    def __init__(self):
        self.calls = []

    def __call__(self, name, arguments):
        self.calls.append((name, copy.deepcopy(arguments)))
        if name == "jackal_exact":
            expression = arguments["expression"]
            value = self._fraction(
                ast.parse(expression.replace("^", "**"), mode="eval").body
            )
            rendered = str(value.numerator)
            if value.denominator != 1:
                rendered += f"/{value.denominator}"
            return {
                "status": "exact",
                "fields": {"parsed": expression, "exact": rendered},
                "formal": False,
            }
        if name == "jackal_divides":
            divisor = int(arguments["a"])
            dividend = int(arguments["b"])
            assert divisor != 0, "module must never delegate a zero divisor"
            verdict = "true" if dividend % divisor == 0 else "false"
            return {
                "status": "exact",
                "fields": {"divides": verdict},
                "formal": False,
            }
        if name == "jackal_xgcd":
            a = int(arguments["a"])
            b = int(arguments["b"])
            old_r, r = a, b
            old_u, u = 1, 0
            old_v, v = 0, 1
            while r != 0:
                q = old_r // r
                old_r, r = r, old_r - q * r
                old_u, u = u, old_u - q * u
                old_v, v = v, old_v - q * v
            if old_r < 0:
                old_r, old_u, old_v = -old_r, -old_u, -old_v
            return {
                "status": "exact",
                "fields": {
                    "g": str(old_r),
                    "u": str(old_u),
                    "v": str(old_v),
                    "exact_cert": '{"kind":"xgcd"}',
                },
                "formal": False,
            }
        if name == "jackal_prime_cert":
            n = int(arguments["n"])
            if _is_prime(n):
                return {
                    "status": "exact",
                    "fields": {
                        "verdict": "prime",
                        "n": str(n),
                        "exact_cert": '{"kind":"prime"}',
                    },
                    "formal": False,
                }
            divisor = next(
                (p for p in range(2, 10_000) if n % p == 0 and p < n), None
            )
            fields = {"verdict": "composite", "n": str(n)}
            if divisor is not None:
                fields["divisor"] = str(divisor)
            return {"status": "exact", "fields": fields, "formal": False}
        if name == "jackal_mod_pow":
            base = int(arguments["base"])
            exp = int(arguments["exp"])
            mod = int(arguments["mod"])
            return {
                "status": "exact",
                "fields": {
                    "r": str(pow(base, exp, mod)),
                    "exact_cert": '{"kind":"mod-pow"}',
                },
                "formal": False,
            }
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


def dispatch(name, arguments, kernel=None):
    kernel = kernel or ExactFixtureKernel()
    result = numbertheory.dispatch_integrated(
        name, arguments, kernel, FIXTURE_IDENTITY
    )
    return result, kernel


class NumberTheorySurfaceTests(unittest.TestCase):
    def test_definitions_form_one_closed_identity_pinned_surface(self):
        definitions = adapter.build_number_theory_tool_definitions(numbertheory)
        self.assertEqual(
            {definition["name"] for definition in definitions},
            adapter.NUMBER_THEORY_TOOL_NAMES,
        )
        self.assertEqual(
            len(definitions), adapter.EXPECTED_NUMBER_THEORY_TOOL_COUNT
        )
        for definition in definitions:
            with self.subTest(tool=definition["name"]):
                self.assertIs(
                    definition["inputSchema"]["additionalProperties"], False
                )
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
        original = numbertheory.tool_definitions
        definitions = original()
        definitions[0] = copy.deepcopy(definitions[0])
        definitions[0]["name"] = "jackal_forged"
        numbertheory.tool_definitions = lambda: definitions
        try:
            with self.assertRaises(adapter.CatalogError):
                adapter.build_number_theory_tool_definitions(numbertheory)
        finally:
            numbertheory.tool_definitions = original

    def test_unknown_tool_and_invalid_arguments_refuse(self):
        result, _ = dispatch("jackal_forged", {})
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "tool-unknown")
        result = numbertheory.dispatch_integrated(
            "jackal_nt_factor", "not-a-dict", ExactFixtureKernel(), FIXTURE_IDENTITY
        )
        self.assertEqual(result["reason"], "tool-unknown")

    def test_kernel_names_are_disjoint_from_runtime_delegates(self):
        self.assertFalse(
            adapter.NUMBER_THEORY_TOOL_NAMES & adapter.NUMBER_THEORY_KERNEL_TOOLS
        )

    def test_refusal_envelope_names_identity_and_non_claims(self):
        result, _ = dispatch("jackal_nt_factor", {"n": "0"})
        self.assertEqual(result["status"], "refused")
        self.assertEqual(
            result["identities"], {"jackal_number_theory_sha256": FIXTURE_IDENTITY}
        )
        self.assertTrue(result["non_claims"])


class FactorTests(unittest.TestCase):
    def test_composite_factorization_certifies_each_prime_and_recomposition(self):
        result, kernel = dispatch("jackal_nt_factor", {"n": "360"})
        self.assertEqual(result["status"], "exact")
        fields = result["fields"]
        self.assertEqual(
            [(f["prime"], f["exponent"]) for f in fields["factors"]],
            [("2", "3"), ("3", "2"), ("5", "1")],
        )
        self.assertEqual(fields["recomposition_check"], "0")
        self.assertEqual(fields["distinct_primes"], "3")
        self.assertEqual(fields["big_omega"], "6")
        for record in fields["factors"]:
            self.assertEqual(record["prime_certificate"], '{"kind":"prime"}')
        prime_calls = [c for c in kernel.calls if c[0] == "jackal_prime_cert"]
        self.assertEqual({c[1]["n"] for c in prime_calls}, {"2", "3", "5"})

    def test_negative_input_recomposes_with_sign(self):
        result, _ = dispatch("jackal_nt_factor", {"n": "-84"})
        self.assertEqual(result["fields"]["sign"], "-1")
        self.assertEqual(result["fields"]["recomposition_check"], "0")

    def test_unit_and_prime_inputs(self):
        result, _ = dispatch("jackal_nt_factor", {"n": "1"})
        self.assertEqual(result["fields"]["factors"], [])
        result, _ = dispatch("jackal_nt_factor", {"n": "97"})
        self.assertEqual(
            [(f["prime"], f["exponent"]) for f in result["fields"]["factors"]],
            [("97", "1")],
        )

    def test_zero_and_malformed_tokens_refuse(self):
        for bad in ("0", "007", "+5", "5.0", "abc", ""):
            result, _ = dispatch("jackal_nt_factor", {"n": bad})
            self.assertEqual(result["status"], "refused", bad)

    def test_budget_refusal_is_named_and_final(self):
        original = numbertheory.POLLARD_ITERATION_BUDGET
        numbertheory.POLLARD_ITERATION_BUDGET = 4
        try:
            hard = str((10**19 + 33) * (10**19 + 97))
            result, _ = dispatch("jackal_nt_factor", {"n": hard})
        finally:
            numbertheory.POLLARD_ITERATION_BUDGET = original
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "factor-budget")


class LcmTests(unittest.TestCase):
    def test_lcm_carries_gcd_certificate_and_kernel_checks(self):
        result, _ = dispatch("jackal_nt_lcm", {"a": "4", "b": "6"})
        fields = result["fields"]
        self.assertEqual(fields["gcd"], "2")
        self.assertEqual(fields["lcm"], "12")
        self.assertEqual(fields["identity_check"], "0")
        self.assertEqual(fields["gcd_certificate"], '{"kind":"xgcd"}')

    def test_negative_operands_produce_nonnegative_lcm(self):
        result, _ = dispatch("jackal_nt_lcm", {"a": "-4", "b": "6"})
        self.assertEqual(result["fields"]["lcm"], "12")

    def test_zero_operand_uses_convention(self):
        result, _ = dispatch("jackal_nt_lcm", {"a": "0", "b": "6"})
        self.assertEqual(result["fields"]["lcm"], "0")
        self.assertEqual(result["fields"]["convention"], "lcm(0, n) = 0")


class ValuationTests(unittest.TestCase):
    def test_valuation_decomposition_is_kernel_verified(self):
        result, _ = dispatch("jackal_nt_valuation", {"n": "48", "p": "2"})
        fields = result["fields"]
        self.assertEqual(fields["valuation"], "4")
        self.assertEqual(fields["p_power"], "16")
        self.assertEqual(fields["cofactor"], "3")
        self.assertEqual(fields["p_divides_cofactor"], "false")

    def test_negative_input_and_zero_valuation(self):
        result, _ = dispatch("jackal_nt_valuation", {"n": "-27", "p": "3"})
        self.assertEqual(result["fields"]["valuation"], "3")
        self.assertEqual(result["fields"]["cofactor"], "-1")
        result, _ = dispatch("jackal_nt_valuation", {"n": "10", "p": "3"})
        self.assertEqual(result["fields"]["valuation"], "0")
        self.assertEqual(result["fields"]["cofactor"], "10")

    def test_composite_p_refuses_with_witness(self):
        result, _ = dispatch("jackal_nt_valuation", {"n": "48", "p": "6"})
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "valuation-not-prime")
        self.assertIn("2", result["detail"])


class IsSquareTests(unittest.TestCase):
    def test_square_and_sandwich_verdicts(self):
        result, _ = dispatch("jackal_nt_is_square", {"n": "49"})
        self.assertEqual(result["fields"]["verdict"], "square")
        self.assertEqual(result["fields"]["root"], "7")
        result, _ = dispatch("jackal_nt_is_square", {"n": "50"})
        fields = result["fields"]
        self.assertEqual(fields["verdict"], "not-square")
        self.assertEqual(fields["floor_root"], "7")
        self.assertEqual(fields["low_gap"], "1")
        self.assertEqual(fields["high_gap"], "14")

    def test_zero_one_and_negative(self):
        result, _ = dispatch("jackal_nt_is_square", {"n": "0"})
        self.assertEqual(result["fields"]["root"], "0")
        result, _ = dispatch("jackal_nt_is_square", {"n": "1"})
        self.assertEqual(result["fields"]["root"], "1")
        result, _ = dispatch("jackal_nt_is_square", {"n": "-4"})
        self.assertEqual(result["fields"]["verdict"], "not-square")
        self.assertEqual(result["fields"]["reason"], "negative")


class CongruenceTests(unittest.TestCase):
    def test_congruent_and_incongruent_pairs(self):
        result, _ = dispatch(
            "jackal_nt_congruence", {"a": "10", "b": "3", "modulus": "7"}
        )
        fields = result["fields"]
        self.assertEqual(fields["congruent"], "true")
        self.assertEqual(fields["difference"], "7")
        self.assertEqual(fields["residue_a"], "3")
        self.assertEqual(fields["residue_b"], "3")
        result, _ = dispatch(
            "jackal_nt_congruence", {"a": "10", "b": "4", "modulus": "7"}
        )
        self.assertEqual(result["fields"]["congruent"], "false")

    def test_negative_values_reduce_to_canonical_residues(self):
        result, _ = dispatch(
            "jackal_nt_congruence", {"a": "-1", "b": "6", "modulus": "7"}
        )
        self.assertEqual(result["fields"]["congruent"], "true")
        self.assertEqual(result["fields"]["residue_a"], "6")

    def test_modulus_one_collapses_everything(self):
        result, _ = dispatch(
            "jackal_nt_congruence", {"a": "5", "b": "-9", "modulus": "1"}
        )
        self.assertEqual(result["fields"]["congruent"], "true")
        self.assertEqual(result["fields"]["residue_a"], "0")


class SqrtModTests(unittest.TestCase):
    def test_residue_roots_are_kernel_certified(self):
        result, _ = dispatch("jackal_nt_sqrt_mod", {"a": "10", "p": "13"})
        fields = result["fields"]
        self.assertEqual(fields["verdict"], "roots")
        self.assertEqual(fields["roots"], ["6", "7"])
        self.assertEqual(fields["euler_value"], "1")
        self.assertEqual(len(fields["square_certificates"]), 2)

    def test_non_residue_returns_euler_witness(self):
        result, _ = dispatch("jackal_nt_sqrt_mod", {"a": "5", "p": "13"})
        fields = result["fields"]
        self.assertEqual(fields["verdict"], "no-root")
        self.assertEqual(fields["euler_value"], "12")
        self.assertEqual(fields["euler_certificate"], '{"kind":"mod-pow"}')

    def test_zero_and_two_and_composite_modulus(self):
        result, _ = dispatch("jackal_nt_sqrt_mod", {"a": "26", "p": "13"})
        self.assertEqual(result["fields"]["roots"], ["0"])
        result, _ = dispatch("jackal_nt_sqrt_mod", {"a": "7", "p": "2"})
        self.assertEqual(result["fields"]["roots"], ["1"])
        result, _ = dispatch("jackal_nt_sqrt_mod", {"a": "3", "p": "15"})
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "sqrt-mod-not-prime")

    def test_tonelli_shanks_hard_prime(self):
        # p = 41 has 2-adic exponent 3 in p-1, exercising the general loop.
        result, _ = dispatch("jackal_nt_sqrt_mod", {"a": "2", "p": "41"})
        fields = result["fields"]
        self.assertEqual(fields["verdict"], "roots")
        for root in fields["roots"]:
            self.assertEqual(pow(int(root), 2, 41), 2)


class LinearDiophantineTests(unittest.TestCase):
    def test_solvable_family_is_kernel_checked(self):
        result, _ = dispatch(
            "jackal_nt_linear_diophantine", {"a": "6", "b": "15", "c": "9"}
        )
        fields = result["fields"]
        self.assertEqual(fields["verdict"], "solvable")
        self.assertEqual(fields["gcd"], "3")
        self.assertEqual(fields["solution_check"], "0")
        self.assertEqual(fields["homogeneous_check"], "0")
        a, b, c = 6, 15, 9
        self.assertEqual(a * int(fields["x"]) + b * int(fields["y"]), c)
        self.assertEqual(
            a * int(fields["x_step"]) + b * int(fields["y_step"]), 0
        )

    def test_obstructed_target_names_the_gcd_verdict(self):
        result, _ = dispatch(
            "jackal_nt_linear_diophantine", {"a": "6", "b": "15", "c": "7"}
        )
        self.assertEqual(result["fields"]["verdict"], "no-solution")
        self.assertEqual(result["fields"]["gcd_divides_c"], "false")

    def test_double_zero_coefficients_refuse(self):
        result, _ = dispatch(
            "jackal_nt_linear_diophantine", {"a": "0", "b": "0", "c": "4"}
        )
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "args")


class PellTests(unittest.TestCase):
    def test_small_fundamental_solution_with_exhaustive_minimality(self):
        result, _ = dispatch("jackal_nt_pell", {"d": "2"})
        fields = result["fields"]
        self.assertEqual((fields["x"], fields["y"]), ("3", "2"))
        self.assertEqual(fields["identity_check"], "0")
        self.assertEqual(fields["minimality"], "exhaustively-verified")
        self.assertEqual(result["field_status"]["fundamental"], "exact")

    def test_d_61_classic_large_solution_is_cf_derived(self):
        result, _ = dispatch("jackal_nt_pell", {"d": "61"})
        fields = result["fields"]
        self.assertEqual(fields["x"], "1766319049")
        self.assertEqual(fields["y"], "226153980")
        self.assertEqual(fields["minimality"], "cf-derived")
        self.assertEqual(result["field_status"]["fundamental"], "checked")
        self.assertTrue(
            any("not independently certified" in claim for claim in result["non_claims"])
        )

    def test_square_d_is_an_exact_degenerate_verdict(self):
        result, _ = dispatch("jackal_nt_pell", {"d": "49"})
        self.assertEqual(result["fields"]["verdict"], "d-is-square")
        self.assertEqual(result["fields"]["root"], "7")

    def test_domain_refusals(self):
        result, _ = dispatch("jackal_nt_pell", {"d": "1"})
        self.assertEqual(result["reason"], "pell-domain")
        result, _ = dispatch("jackal_nt_pell", {"d": "-3"})
        self.assertEqual(result["status"], "refused")


class ModObstructionTests(unittest.TestCase):
    def test_sum_of_two_squares_obstruction_mod_4(self):
        result, _ = dispatch(
            "jackal_nt_mod_obstruction",
            {"expression": "x^2 + y^2 - 3", "modulus": "4", "variables": "x,y"},
        )
        fields = result["fields"]
        self.assertEqual(fields["verdict"], "obstruction")
        self.assertEqual(fields["classes_checked"], "16")
        self.assertEqual(len(fields["residue_table"]), 16)
        for row in fields["residue_table"]:
            self.assertEqual(row["divisible"], "false")

    def test_solvable_congruence_returns_kernel_verified_witness(self):
        result, _ = dispatch(
            "jackal_nt_mod_obstruction",
            {"expression": "x^2 - 1", "modulus": "8"},
        )
        fields = result["fields"]
        self.assertEqual(fields["verdict"], "no-obstruction")
        self.assertEqual(fields["witness"]["x"], "1")
        self.assertEqual(fields["witness"]["divisible"], "true")

    def test_budget_and_fragment_refusals(self):
        result, _ = dispatch(
            "jackal_nt_mod_obstruction",
            {"expression": "x^2 + y^2 - 3", "modulus": "17", "variables": "x,y"},
        )
        self.assertEqual(result["reason"], "obstruction-budget")
        result, _ = dispatch(
            "jackal_nt_mod_obstruction",
            {"expression": "x/2", "modulus": "4"},
        )
        self.assertEqual(result["reason"], "obstruction-fragment")
        result, _ = dispatch(
            "jackal_nt_mod_obstruction",
            {"expression": "x + y", "modulus": "4"},
        )
        self.assertEqual(result["reason"], "obstruction-fragment")

    def test_every_class_is_kernel_decided_never_sampled(self):
        _, kernel = dispatch(
            "jackal_nt_mod_obstruction",
            {"expression": "x^2 + y^2 - 3", "modulus": "4", "variables": "x,y"},
        )
        divides_calls = [c for c in kernel.calls if c[0] == "jackal_divides"]
        self.assertEqual(len(divides_calls), 16)


class VietaDescentTests(unittest.TestCase):
    def test_imo_1988_p6_instance_descends_to_the_square(self):
        result, _ = dispatch("jackal_nt_vieta_descent", {"a": "30", "b": "112"})
        fields = result["fields"]
        self.assertEqual(fields["verdict"], "quotient-is-square")
        self.assertEqual(fields["k"], "4")
        self.assertEqual(fields["square_root"], "2")
        self.assertEqual(fields["square_check"], "0")
        chain = fields["descent_chain"]
        self.assertEqual(fields["chain_length"], str(len(chain)))
        self.assertEqual(chain[0]["from"], ["112", "30"])
        for step in chain:
            self.assertEqual(step["product_check"], "0")
            self.assertEqual(step["invariant_check"], "0")
        self.assertEqual(chain[-1]["companion"], "0")

    def test_trivial_and_symmetric_instances(self):
        result, _ = dispatch("jackal_nt_vieta_descent", {"a": "1", "b": "1"})
        self.assertEqual(result["fields"]["k"], "1")
        self.assertEqual(result["fields"]["square_root"], "1")
        result, _ = dispatch("jackal_nt_vieta_descent", {"a": "2", "b": "8"})
        self.assertEqual(result["fields"]["k"], "4")

    def test_false_instance_8_57_is_rejected_by_kernel_divisibility(self):
        result, _ = dispatch("jackal_nt_vieta_descent", {"a": "8", "b": "57"})
        fields = result["fields"]
        self.assertEqual(result["status"], "exact")
        self.assertEqual(fields["verdict"], "not-a-solution")
        self.assertEqual(fields["denominator_divides_numerator"], "false")

    def test_positivity_is_required(self):
        for bad in ({"a": "0", "b": "3"}, {"a": "-8", "b": "2"}):
            result, _ = dispatch("jackal_nt_vieta_descent", bad)
            self.assertEqual(result["status"], "refused", bad)


class DelegationDisciplineTests(unittest.TestCase):
    def test_every_exact_result_names_delegation_and_identity(self):
        cases = [
            ("jackal_nt_factor", {"n": "360"}),
            ("jackal_nt_lcm", {"a": "4", "b": "6"}),
            ("jackal_nt_valuation", {"n": "48", "p": "2"}),
            ("jackal_nt_is_square", {"n": "50"}),
            ("jackal_nt_congruence", {"a": "10", "b": "3", "modulus": "7"}),
            ("jackal_nt_sqrt_mod", {"a": "10", "p": "13"}),
            ("jackal_nt_linear_diophantine", {"a": "6", "b": "15", "c": "9"}),
            ("jackal_nt_pell", {"d": "2"}),
            ("jackal_nt_mod_obstruction", {"expression": "x^2 - 1", "modulus": "8"}),
            ("jackal_nt_vieta_descent", {"a": "8", "b": "2"}),
        ]
        for name, arguments in cases:
            with self.subTest(tool=name):
                result, kernel = dispatch(name, arguments)
                self.assertEqual(result["status"], "exact")
                self.assertIs(result["formal"], False)
                self.assertEqual(
                    result["consequence_ceiling"],
                    numbertheory.CONSEQUENCE_CEILING,
                )
                self.assertEqual(
                    result["identities"],
                    {"jackal_number_theory_sha256": FIXTURE_IDENTITY},
                )
                self.assertTrue(kernel.calls, "no delegation happened")
                self.assertEqual(len(result["delegated_to"]), len(kernel.calls))
                self.assertTrue(result["non_claims"])

    def test_kernel_refusal_propagates_without_substitution(self):
        class RefusingKernel(ExactFixtureKernel):
            def __call__(self, name, arguments):
                if name == "jackal_divides":
                    return {
                        "status": "refused",
                        "reason": "int-budget",
                        "detail": "fixture refusal",
                    }
                return super().__call__(name, arguments)

        result, _ = dispatch(
            "jackal_nt_congruence",
            {"a": "10", "b": "3", "modulus": "7"},
            RefusingKernel(),
        )
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "kernel-refused:int-budget")

    def test_kernel_error_fails_closed(self):
        class BrokenKernel(ExactFixtureKernel):
            def __call__(self, name, arguments):
                return "not-an-object"

        result, _ = dispatch(
            "jackal_nt_is_square", {"n": "49"}, BrokenKernel()
        )
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "kernel-error")


class MCPServerValidationTests(unittest.TestCase):
    def _definitions(self):
        return [
            copy.deepcopy(definition)
            for definition in adapter.build_number_theory_tool_definitions(
                numbertheory
            )
        ]

    def test_identity_without_module_is_rejected(self):
        with self.assertRaises(ValueError):
            adapter.MCPServer(
                runtime_root=".",
                launcher="/bin/false",
                tool_definitions=[],
                runtime_environment={"PATH": "/usr/bin"},
                number_theory_identity=FIXTURE_IDENTITY,
            )

    def test_definitions_without_dispatcher_are_rejected(self):
        with self.assertRaises(ValueError):
            adapter.MCPServer(
                runtime_root=".",
                launcher="/bin/false",
                tool_definitions=self._definitions(),
                runtime_environment={"PATH": "/usr/bin"},
            )

    def test_module_with_missing_definitions_is_rejected(self):
        with self.assertRaises(ValueError):
            adapter.MCPServer(
                runtime_root=".",
                launcher="/bin/false",
                tool_definitions=[],
                runtime_environment={"PATH": "/usr/bin"},
                number_theory_module=numbertheory,
                number_theory_identity=FIXTURE_IDENTITY,
            )

    def test_module_with_valid_surface_is_accepted(self):
        server = adapter.MCPServer(
            runtime_root=".",
            launcher="/bin/false",
            tool_definitions=self._definitions(),
            runtime_environment={"PATH": "/usr/bin"},
            number_theory_module=numbertheory,
            number_theory_identity=FIXTURE_IDENTITY,
        )
        self.assertEqual(
            server._number_theory_tools, adapter.NUMBER_THEORY_TOOL_NAMES
        )


if __name__ == "__main__":
    unittest.main()
