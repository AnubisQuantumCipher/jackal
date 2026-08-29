#!/usr/bin/env python3 -B
"""Additive AI-facing certified number-theory workflows (JACKAL Number Theory 1.0).

This module is identity-pinned wrapper orchestration, not a second calculator.
It follows de Bruijn's criterion deliberately: an untrusted discovery layer
(trial division, Pollard rho, Tonelli-Shanks, continued fractions, Vieta
jumping, residue scans) may search creatively, but every arithmetic claim that
reaches a reported field is verified by delegated calls into the sealed JACKAL
runtime.  Python proposes; the pinned kernel decides.

Proof schemas carried by this surface:

- structured divisibility, congruence, lcm, valuation, and square objects;
- certified prime factorization (per-factor Pratt certificates plus a
  kernel-checked recomposition identity);
- Tonelli-Shanks modular square roots with kernel-checked Euler criteria;
- linear Diophantine solvability with Bezout certificates;
- Pell fundamental solutions with kernel-checked identities;
- exhaustive modular-obstruction certificates (every residue class decided by
  the kernel, never sampled);
- Vieta-jumping descent chains in the shape of IMO 1988 Problem 6, with every
  companion root, product identity, and state invariant kernel-verified down
  to the terminal square.

A refusal is an answer.  When discovery cannot complete within budget, or a
claim cannot be kernel-verified, this module refuses with a named reason and
never substitutes local arithmetic for the sealed runtime's verdict.
"""

from __future__ import annotations

import copy
import math
import re
from typing import Callable


NUMBER_THEORY_TOOL_NAMES = frozenset(
    {
        "jackal_nt_congruence",
        "jackal_nt_factor",
        "jackal_nt_is_square",
        "jackal_nt_lcm",
        "jackal_nt_linear_diophantine",
        "jackal_nt_mod_obstruction",
        "jackal_nt_pell",
        "jackal_nt_sqrt_mod",
        "jackal_nt_valuation",
        "jackal_nt_vieta_descent",
    }
)

CONSEQUENCE_CEILING = "informational"
MAX_NT_INT_DIGITS = 512
MAX_FACTOR_INPUT_DIGITS = 512
MAX_PRIME_CERT_DIGITS = 60
MAX_FACTOR_DISTINCT_PRIMES = 64
POLLARD_ITERATION_BUDGET = 400_000
MAX_VALUATION_EXPONENT = 1 << 20
MAX_OBSTRUCTION_MODULUS = 128
MAX_OBSTRUCTION_CHECKS = 256
MAX_EXPRESSION_BYTES = 1024
MAX_PELL_D_DIGITS = 14
MAX_PELL_PERIOD = 200_000
MAX_PELL_SOLUTION_DIGITS = 2000
PELL_EXHAUSTIVE_MINIMALITY_LIMIT = 32
MAX_DESCENT_STEPS = 128

CANONICAL_SIGNED_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)\Z", re.ASCII)
OBSTRUCTION_EXPRESSION = re.compile(r"[0-9xy+\-*^() ]+\Z", re.ASCII)
X_TOKEN = re.compile(r"(?<![A-Za-z0-9_])x(?![A-Za-z0-9_])", re.ASCII)
Y_TOKEN = re.compile(r"(?<![A-Za-z0-9_])y(?![A-Za-z0-9_])", re.ASCII)

_SMALL_PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)


class Refusal(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


_KERNEL: object | None = None
_IDENTITY: str | None = None
_TRACE: list[dict] = []


def _identity() -> str:
    if _IDENTITY is None:
        raise RuntimeError(
            "number-theory identity is unavailable outside integrated dispatch"
        )
    return _IDENTITY


def _refusal(reason: str, detail: str) -> dict:
    return {
        "status": "refused",
        "reason": reason,
        "detail": detail,
        "consequence_ceiling": CONSEQUENCE_CEILING,
        "identities": {"jackal_number_theory_sha256": _identity()},
        "non_claims": [
            "A refusal is an answer; no weaker lane or local arithmetic was substituted",
            "No divisibility, primality, solvability, or descent conclusion was established",
        ],
    }


def _kernel_call(tool: str, arguments: dict) -> dict:
    if _KERNEL is None:
        raise Refusal("kernel-unavailable", "number-theory module is not attached to JACKAL")
    result = _KERNEL.call(tool, arguments)
    if not isinstance(result, dict):
        raise Refusal("kernel-error", "JACKAL returned a non-object")
    trace = {
        "tool": tool,
        "arguments": copy.deepcopy(arguments),
        "status": result.get("status", "unknown"),
    }
    fields = result.get("fields")
    if isinstance(fields, dict) and isinstance(fields.get("parsed"), str):
        trace["parsed"] = fields["parsed"]
    _TRACE.append(trace)
    if result.get("status") == "refused":
        raise Refusal(
            f"kernel-refused:{result.get('reason', 'unknown')}",
            str(result.get("detail", "the delegated JACKAL lane refused")),
        )
    return result


def _field(result: dict, key: str, subject: str) -> str:
    fields = result.get("fields")
    if not isinstance(fields, dict) or not isinstance(fields.get(key), str):
        raise Refusal("kernel-error", f"delegated {subject} result omitted field {key!r}")
    return fields[key]


def _exact(expression: str) -> str:
    if len(expression.encode("utf-8")) > MAX_EXPRESSION_BYTES * 8:
        raise Refusal("int-budget", "delegated expression exceeds the wrapper byte budget")
    result = _kernel_call("jackal_exact", {"expression": expression})
    if result.get("status") != "exact":
        raise Refusal("kernel-error", "delegated exact lane returned a non-exact status")
    return _field(result, "exact", "exact")


def _exact_int(expression: str, subject: str) -> tuple[str, int]:
    canonical = _exact(expression)
    if "/" in canonical:
        raise Refusal("nt-internal", f"{subject} was expected to be an integer")
    return canonical, int(canonical)


def _is_zero(expression: str) -> bool:
    return _exact(expression) == "0"


def _require_zero(expression: str, subject: str) -> str:
    canonical = _exact(expression)
    if canonical != "0":
        raise Refusal("nt-internal", f"kernel verification failed for {subject}")
    return canonical


def _require_positive(expression: str, subject: str) -> str:
    canonical = _exact(expression)
    if canonical == "0" or canonical.startswith("-"):
        raise Refusal("nt-internal", f"kernel verification failed for {subject}")
    return canonical


def _kernel_divides(divisor: str, dividend: str) -> tuple[bool, dict]:
    result = _kernel_call("jackal_divides", {"a": divisor, "b": dividend})
    verdict = _field(result, "divides", "divides")
    if verdict not in {"true", "false"}:
        raise Refusal("kernel-error", "delegated divisibility verdict is invalid")
    return verdict == "true", result


def _kernel_prime(n: str) -> dict:
    result = _kernel_call("jackal_prime_cert", {"n": n})
    verdict = _field(result, "verdict", "prime-cert")
    if verdict not in {"prime", "composite"}:
        raise Refusal("kernel-error", "delegated primality verdict is invalid")
    return result


def _kernel_mod_pow(base: str, exp: str, mod: str) -> dict:
    return _kernel_call("jackal_mod_pow", {"base": base, "exp": exp, "mod": mod})


def _kernel_xgcd(a: str, b: str) -> dict:
    return _kernel_call("jackal_xgcd", {"a": a, "b": b})


def _cert_of(result: dict) -> str | None:
    fields = result.get("fields")
    if isinstance(fields, dict) and isinstance(fields.get("exact_cert"), str):
        return fields["exact_cert"]
    return None


def _int_arg(
    arguments: dict,
    key: str,
    subject: str,
    *,
    allow_negative: bool = True,
    allow_zero: bool = True,
    max_digits: int = MAX_NT_INT_DIGITS,
) -> tuple[str, int]:
    value = arguments.get(key)
    if not isinstance(value, str) or CANONICAL_SIGNED_INTEGER.fullmatch(value) is None:
        raise Refusal("args", f"{subject} must be a canonical integer token")
    if len(value.lstrip("-")) > max_digits:
        raise Refusal("int-budget", f"{subject} exceeds the {max_digits}-digit budget")
    parsed = int(value)
    if not allow_negative and parsed < 0:
        raise Refusal("args", f"{subject} must be nonnegative")
    if not allow_zero and parsed == 0:
        raise Refusal("args", f"{subject} must be nonzero")
    return value, parsed


def _result(
    lane: str,
    parsed: dict,
    fields: dict,
    field_status: dict,
    non_claims: list[str],
) -> dict:
    return {
        "status": "exact",
        "lane": lane,
        "formal": False,
        "consequence_ceiling": CONSEQUENCE_CEILING,
        "parsed": parsed,
        "fields": fields,
        "field_status": field_status,
        "delegated_to": list(_TRACE),
        "identities": {"jackal_number_theory_sha256": _identity()},
        "non_claims": non_claims,
    }


_BASE_NON_CLAIMS = [
    "Every reported arithmetic claim was verified by delegated sealed-runtime calls; the discovery layer is untrusted by design",
    "NOT formal-bounded: the orchestration is identity-pinned and tested, not Lean-proved",
    "The delegation trace is reproducibility metadata, not an independent certificate",
]


# --------------------------------------------------------------------------
# Untrusted discovery helpers (never load-bearing: every claim re-verified)
# --------------------------------------------------------------------------


def _is_probable_prime(n: int) -> bool:
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p
    d = n - 1
    r = 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for a in _SMALL_PRIMES:
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


def _pollard_rho(n: int, budget: list[int]) -> int:
    if n % 2 == 0:
        return 2
    seed = 1
    while True:
        seed += 1
        x = seed
        y = seed
        c = seed | 1
        d = 1
        while d == 1:
            budget[0] -= 1
            if budget[0] <= 0:
                raise Refusal(
                    "factor-budget",
                    "the untrusted discovery layer exhausted its factorization budget; no partial factorization is claimed",
                )
            x = (x * x + c) % n
            y = (y * y + c) % n
            y = (y * y + c) % n
            d = math.gcd(abs(x - y), n)
        if d != n:
            return d


def _discover_factorization(n: int) -> dict[int, int]:
    factors: dict[int, int] = {}
    budget = [POLLARD_ITERATION_BUDGET]
    remaining = n
    for p in _SMALL_PRIMES:
        while remaining % p == 0:
            factors[p] = factors.get(p, 0) + 1
            remaining //= p
    trial = 41
    while trial * trial <= remaining and trial < 100_000:
        while remaining % trial == 0:
            factors[trial] = factors.get(trial, 0) + 1
            remaining //= trial
        trial += 2
    stack = [remaining] if remaining > 1 else []
    while stack:
        m = stack.pop()
        if m == 1:
            continue
        if _is_probable_prime(m):
            factors[m] = factors.get(m, 0) + 1
            continue
        divisor = _pollard_rho(m, budget)
        if divisor in (1, m):
            raise Refusal(
                "factor-budget",
                "the untrusted discovery layer could not split a composite cofactor within budget",
            )
        stack.append(divisor)
        stack.append(m // divisor)
        if len(factors) + len(stack) > MAX_FACTOR_DISTINCT_PRIMES:
            raise Refusal(
                "factor-budget",
                "the factorization exceeds the distinct-prime budget",
            )
    return factors


def _tonelli_shanks(a: int, p: int) -> int:
    if p % 4 == 3:
        return pow(a, (p + 1) // 4, p)
    q = p - 1
    s = 0
    while q % 2 == 0:
        q //= 2
        s += 1
    z = 2
    while pow(z, (p - 1) // 2, p) != p - 1:
        z += 1
    m = s
    c = pow(z, q, p)
    t = pow(a, q, p)
    r = pow(a, (q + 1) // 2, p)
    while t != 1:
        i = 0
        probe = t
        while probe != 1:
            probe = (probe * probe) % p
            i += 1
            if i == m:
                raise Refusal("nt-internal", "Tonelli-Shanks discovery failed unexpectedly")
        b = pow(c, 1 << (m - i - 1), p)
        m = i
        c = (b * b) % p
        t = (t * c) % p
        r = (r * b) % p
    return r


def _pell_continued_fraction(d: int, root: int) -> tuple[int, int, int]:
    """Fundamental solution of x^2 - d*y^2 = 1 via the sqrt(d) expansion."""
    m, k, a = 0, 1, root
    p_prev, p_curr = 1, root
    q_prev, q_curr = 0, 1
    period = 0
    for _ in range(MAX_PELL_PERIOD):
        m = a * k - m
        k = (d - m * m) // k
        a = (root + m) // k
        p_prev, p_curr = p_curr, a * p_curr + p_prev
        q_prev, q_curr = q_curr, a * q_curr + q_prev
        period += 1
        if p_prev * p_prev - d * q_prev * q_prev == 1:
            return p_prev, q_prev, period
    raise Refusal(
        "pell-budget",
        "the continued-fraction expansion exceeded the period budget",
    )


# --------------------------------------------------------------------------
# Tool implementations (kernel-verified)
# --------------------------------------------------------------------------


def _factor_tool(arguments: dict) -> dict:
    token, value = _int_arg(
        arguments, "n", "n", allow_zero=False, max_digits=MAX_FACTOR_INPUT_DIGITS
    )
    sign = "-1" if value < 0 else "1"
    magnitude = abs(value)
    factor_records: list[dict] = []
    if magnitude == 1:
        recomposition = _require_zero(f"({token})-({sign})", "unit recomposition")
        return _result(
            "nt-factor-exact-delegated-v1",
            {"n": token},
            {
                "sign": sign,
                "factors": factor_records,
                "recomposition_check": recomposition,
                "distinct_primes": "0",
                "big_omega": "0",
            },
            {"factors": "exact", "recomposition_check": "exact"},
            _BASE_NON_CLAIMS
            + ["A unit has the empty factorization; the recomposition identity is kernel-checked"],
        )
    discovered = _discover_factorization(magnitude)
    big_omega = 0
    for prime in sorted(discovered):
        exponent = discovered[prime]
        big_omega += exponent
        prime_token = str(prime)
        if len(prime_token) > MAX_PRIME_CERT_DIGITS:
            raise Refusal(
                "factor-cert-budget",
                "a discovered prime factor exceeds the sealed prime-certificate budget (10^60)",
            )
        verdict = _kernel_prime(prime_token)
        if _field(verdict, "verdict", "prime-cert") != "prime":
            raise Refusal(
                "nt-internal",
                "the sealed runtime rejected a discovered prime factor",
            )
        record: dict = {
            "prime": prime_token,
            "exponent": str(exponent),
        }
        certificate = _cert_of(verdict)
        if certificate is not None:
            record["prime_certificate"] = certificate
        factor_records.append(record)
    terms = []
    for record in factor_records:
        if record["exponent"] == "1":
            terms.append(f"({record['prime']})")
        else:
            terms.append(f"({record['prime']})^{record['exponent']}")
    recomposition_expr = "*".join(terms)
    if sign == "-1":
        recomposition_expr = f"(-1)*{recomposition_expr}"
    recomposition = _require_zero(
        f"({token})-({recomposition_expr})", "factor recomposition"
    )
    return _result(
        "nt-factor-exact-delegated-v1",
        {"n": token},
        {
            "sign": sign,
            "factors": factor_records,
            "recomposition_check": recomposition,
            "distinct_primes": str(len(factor_records)),
            "big_omega": str(big_omega),
        },
        {"factors": "exact", "recomposition_check": "exact"},
        _BASE_NON_CLAIMS
        + [
            "Each listed prime carries a sealed-runtime Pratt certificate; the product identity n = sign * prod(p^e) is kernel-checked",
        ],
    )


def _lcm_tool(arguments: dict) -> dict:
    a_token, a_value = _int_arg(arguments, "a", "a")
    b_token, b_value = _int_arg(arguments, "b", "b")
    if a_value == 0 or b_value == 0:
        zero = _exact("0")
        return _result(
            "nt-lcm-exact-delegated-v1",
            {"a": a_token, "b": b_token},
            {"lcm": zero, "convention": "lcm(0, n) = 0"},
            {"lcm": "exact"},
            _BASE_NON_CLAIMS
            + ["lcm with a zero argument is 0 by convention; no divisibility chain applies"],
        )
    xg = _kernel_xgcd(a_token, b_token)
    g = _field(xg, "g", "xgcd")
    product_abs, product_value = _exact_int(
        f"({a_token})*({b_token})", "product magnitude"
    )
    if product_value < 0:
        product_abs, _ = _exact_int(f"-({product_abs})", "product magnitude")
    lcm, _ = _exact_int(f"({product_abs})/({g})", "lcm")
    identity = _require_zero(
        f"(({g})*({lcm}))-({product_abs})", "gcd*lcm identity"
    )
    a_divides, _ = _kernel_divides(a_token, lcm)
    b_divides, _ = _kernel_divides(b_token, lcm)
    if not a_divides or not b_divides:
        raise Refusal("nt-internal", "kernel divisibility check failed for lcm")
    fields: dict = {
        "gcd": g,
        "lcm": lcm,
        "identity_check": identity,
        "a_divides_lcm": "true",
        "b_divides_lcm": "true",
    }
    certificate = _cert_of(xg)
    if certificate is not None:
        fields["gcd_certificate"] = certificate
    return _result(
        "nt-lcm-exact-delegated-v1",
        {"a": a_token, "b": b_token},
        fields,
        {"gcd": "exact", "lcm": "exact", "identity_check": "exact"},
        _BASE_NON_CLAIMS
        + [
            "The gcd carries the sealed runtime's Bezout certificate; gcd*lcm = |a*b| and both divisibilities are kernel-checked",
        ],
    )


def _valuation_tool(arguments: dict) -> dict:
    n_token, n_value = _int_arg(arguments, "n", "n", allow_zero=False)
    p_token, p_value = _int_arg(
        arguments, "p", "p", allow_negative=False, allow_zero=False
    )
    if p_value < 2:
        raise Refusal("args", "p must be at least 2")
    verdict = _kernel_prime(p_token)
    if _field(verdict, "verdict", "prime-cert") != "prime":
        divisor = ""
        fields = verdict.get("fields")
        if isinstance(fields, dict) and isinstance(fields.get("divisor"), str):
            divisor = f" (witness divisor {fields['divisor']})"
        raise Refusal(
            "valuation-not-prime",
            f"p is composite by sealed-runtime certificate{divisor}",
        )
    magnitude = abs(n_value)
    exponent = 0
    remaining = magnitude
    while remaining % p_value == 0:
        remaining //= p_value
        exponent += 1
        if exponent > MAX_VALUATION_EXPONENT:
            raise Refusal("int-budget", "the valuation exceeds the exponent budget")
    power_expr = f"({p_token})^{exponent}" if exponent > 0 else "1"
    p_power, _ = _exact_int(power_expr, "p^v")
    cofactor, _ = _exact_int(f"({n_token})/({power_expr})", "cofactor")
    still_divides, _ = _kernel_divides(p_token, cofactor)
    if still_divides:
        raise Refusal("nt-internal", "kernel found a larger valuation than discovery")
    prime_certificate = _cert_of(verdict)
    fields = {
        "valuation": str(exponent),
        "p_power": p_power,
        "cofactor": cofactor,
        "p_divides_cofactor": "false",
    }
    if prime_certificate is not None:
        fields["prime_certificate"] = prime_certificate
    return _result(
        "nt-valuation-exact-delegated-v1",
        {"n": n_token, "p": p_token},
        fields,
        {"valuation": "exact", "p_power": "exact", "cofactor": "exact"},
        _BASE_NON_CLAIMS
        + [
            "n = p^v * cofactor holds by kernel-exact division and p does not divide the cofactor by kernel verdict; p is prime by sealed certificate",
        ],
    )


def _is_square_tool(arguments: dict) -> dict:
    token, value = _int_arg(arguments, "n", "n")
    if value < 0:
        negativity = _require_positive(f"-({token})", "negativity")
        return _result(
            "nt-is-square-exact-delegated-v1",
            {"n": token},
            {"verdict": "not-square", "reason": "negative", "magnitude": negativity},
            {"verdict": "exact"},
            _BASE_NON_CLAIMS
            + ["A negative integer is not an integer square; the sign was kernel-checked"],
        )
    root = math.isqrt(value)
    if root * root == value:
        check = _require_zero(f"(({root})*({root}))-({token})", "square identity")
        return _result(
            "nt-is-square-exact-delegated-v1",
            {"n": token},
            {"verdict": "square", "root": str(root), "square_check": check},
            {"verdict": "exact", "root": "exact"},
            _BASE_NON_CLAIMS
            + ["root^2 = n is kernel-checked; the root is the discovery witness"],
        )
    low_gap = _require_positive(
        f"({token})-(({root})*({root}))", "lower sandwich gap"
    )
    high_gap = _require_positive(
        f"((({root})+1)*(({root})+1))-({token})", "upper sandwich gap"
    )
    return _result(
        "nt-is-square-exact-delegated-v1",
        {"n": token},
        {
            "verdict": "not-square",
            "floor_root": str(root),
            "low_gap": low_gap,
            "high_gap": high_gap,
        },
        {"verdict": "exact"},
        _BASE_NON_CLAIMS
        + [
            "floor_root^2 < n < (floor_root+1)^2 is kernel-checked, so n lies strictly between consecutive squares",
        ],
    )


def _congruence_tool(arguments: dict) -> dict:
    a_token, a_value = _int_arg(arguments, "a", "a")
    b_token, b_value = _int_arg(arguments, "b", "b")
    m_token, m_value = _int_arg(
        arguments, "modulus", "modulus", allow_negative=False, allow_zero=False
    )
    difference = _exact(f"({a_token})-({b_token})")
    congruent, _ = _kernel_divides(m_token, difference)
    residues: dict[str, str] = {}
    for key, source_token, source_value in (
        ("residue_a", a_token, a_value),
        ("residue_b", b_token, b_value),
    ):
        residue = source_value % m_value
        residue_token = str(residue)
        reduced, _ = _kernel_divides(
            m_token, _exact(f"({source_token})-({residue_token})")
        )
        if not reduced:
            raise Refusal("nt-internal", "kernel rejected a discovered residue")
        if residue != 0:
            _require_positive(f"({m_token})-({residue_token})", "residue range")
        residues[key] = residue_token
    return _result(
        "nt-congruence-exact-delegated-v1",
        {"a": a_token, "b": b_token, "modulus": m_token},
        {
            "congruent": "true" if congruent else "false",
            "difference": difference,
            "residue_a": residues["residue_a"],
            "residue_b": residues["residue_b"],
        },
        {"congruent": "exact", "residue_a": "exact", "residue_b": "exact"},
        _BASE_NON_CLAIMS
        + [
            "The congruence verdict is the sealed runtime's divisibility decision on a-b; each residue is kernel-verified to be congruent and in range",
        ],
    )


def _sqrt_mod_tool(arguments: dict) -> dict:
    a_token, a_value = _int_arg(arguments, "a", "a")
    p_token, p_value = _int_arg(
        arguments, "p", "p", allow_negative=False, allow_zero=False
    )
    if p_value < 2:
        raise Refusal("args", "p must be at least 2")
    verdict = _kernel_prime(p_token)
    if _field(verdict, "verdict", "prime-cert") != "prime":
        raise Refusal(
            "sqrt-mod-not-prime", "p is composite by sealed-runtime certificate"
        )
    prime_certificate = _cert_of(verdict)
    a_residue = a_value % p_value
    residue_token = str(a_residue)
    reduced, _ = _kernel_divides(p_token, _exact(f"({a_token})-({residue_token})"))
    if not reduced:
        raise Refusal("nt-internal", "kernel rejected the reduced residue")
    common_fields: dict = {"reduced_a": residue_token}
    if prime_certificate is not None:
        common_fields["prime_certificate"] = prime_certificate
    if a_residue == 0:
        square_check = _field(
            _kernel_mod_pow("0", "2", p_token), "r", "mod-pow"
        )
        if square_check != "0":
            raise Refusal("nt-internal", "kernel rejected the zero root")
        return _result(
            "nt-sqrt-mod-exact-delegated-v1",
            {"a": a_token, "p": p_token},
            {**common_fields, "verdict": "roots", "roots": ["0"]},
            {"verdict": "exact", "roots": "exact"},
            _BASE_NON_CLAIMS
            + ["a is divisible by p, so 0 is the unique square root modulo p"],
        )
    if p_value == 2:
        return _result(
            "nt-sqrt-mod-exact-delegated-v1",
            {"a": a_token, "p": p_token},
            {**common_fields, "verdict": "roots", "roots": ["1"]},
            {"verdict": "exact", "roots": "exact"},
            _BASE_NON_CLAIMS + ["Modulo 2 every odd residue has the square root 1"],
        )
    euler_exponent, _ = _exact_int(f"(({p_token})-1)/2", "Euler exponent")
    euler = _kernel_mod_pow(residue_token, euler_exponent, p_token)
    euler_value = _field(euler, "r", "mod-pow")
    minus_one, _ = _exact_int(f"({p_token})-1", "p-1")
    euler_certificate = _cert_of(euler)
    if euler_value == minus_one:
        fields = {
            **common_fields,
            "verdict": "no-root",
            "euler_exponent": euler_exponent,
            "euler_value": euler_value,
        }
        if euler_certificate is not None:
            fields["euler_certificate"] = euler_certificate
        return _result(
            "nt-sqrt-mod-exact-delegated-v1",
            {"a": a_token, "p": p_token},
            fields,
            {"verdict": "exact", "euler_value": "exact"},
            _BASE_NON_CLAIMS
            + [
                "a^((p-1)/2) = p-1 (mod p) is a sealed-runtime certificate, so a is a quadratic non-residue by Euler's criterion",
            ],
        )
    if euler_value != "1":
        raise Refusal("nt-internal", "Euler criterion returned an unexpected value")
    root = _tonelli_shanks(a_residue, p_value)
    roots: list[str] = []
    square_certificates: list[str] = []
    for candidate in sorted({root, p_value - root}):
        candidate_token = str(candidate)
        squared = _kernel_mod_pow(candidate_token, "2", p_token)
        if _field(squared, "r", "mod-pow") != residue_token:
            raise Refusal("nt-internal", "kernel rejected a discovered square root")
        roots.append(candidate_token)
        certificate = _cert_of(squared)
        if certificate is not None:
            square_certificates.append(certificate)
    fields = {
        **common_fields,
        "verdict": "roots",
        "roots": roots,
        "euler_exponent": euler_exponent,
        "euler_value": euler_value,
    }
    if euler_certificate is not None:
        fields["euler_certificate"] = euler_certificate
    if square_certificates:
        fields["square_certificates"] = square_certificates
    return _result(
        "nt-sqrt-mod-exact-delegated-v1",
        {"a": a_token, "p": p_token},
        fields,
        {"verdict": "exact", "roots": "exact", "euler_value": "exact"},
        _BASE_NON_CLAIMS
        + [
            "Each root r satisfies r^2 = a (mod p) by sealed-runtime certificate; Tonelli-Shanks was only the untrusted discovery path",
        ],
    )


def _linear_diophantine_tool(arguments: dict) -> dict:
    a_token, a_value = _int_arg(arguments, "a", "a")
    b_token, b_value = _int_arg(arguments, "b", "b")
    c_token, _ = _int_arg(arguments, "c", "c")
    if a_value == 0 and b_value == 0:
        raise Refusal("args", "a and b must not both be zero")
    xg = _kernel_xgcd(a_token, b_token)
    g = _field(xg, "g", "xgcd")
    u = _field(xg, "u", "xgcd")
    v = _field(xg, "v", "xgcd")
    gcd_certificate = _cert_of(xg)
    solvable, _ = _kernel_divides(g, c_token)
    base_fields: dict = {"gcd": g, "bezout_u": u, "bezout_v": v}
    if gcd_certificate is not None:
        base_fields["gcd_certificate"] = gcd_certificate
    if not solvable:
        return _result(
            "nt-linear-diophantine-exact-delegated-v1",
            {"a": a_token, "b": b_token, "c": c_token},
            {
                **base_fields,
                "verdict": "no-solution",
                "gcd_divides_c": "false",
            },
            {"verdict": "exact", "gcd": "exact"},
            _BASE_NON_CLAIMS
            + [
                "gcd(a,b) does not divide c by sealed-runtime verdict; insolvability follows by the linear-combination divisibility rule gcd(a,b) | a*x+b*y",
            ],
        )
    scale, _ = _exact_int(f"({c_token})/({g})", "solution scale")
    x0, _ = _exact_int(f"({u})*({scale})", "particular x")
    y0, _ = _exact_int(f"({v})*({scale})", "particular y")
    solution_check = _require_zero(
        f"((({a_token})*({x0}))+(({b_token})*({y0})))-({c_token})",
        "particular solution",
    )
    x_step, _ = _exact_int(f"({b_token})/({g})", "x step")
    y_step, _ = _exact_int(f"-(({a_token})/({g}))", "y step")
    homogeneous_check = _require_zero(
        f"(({a_token})*({x_step}))+(({b_token})*({y_step}))",
        "homogeneous step",
    )
    return _result(
        "nt-linear-diophantine-exact-delegated-v1",
        {"a": a_token, "b": b_token, "c": c_token},
        {
            **base_fields,
            "verdict": "solvable",
            "x": x0,
            "y": y0,
            "solution_check": solution_check,
            "x_step": x_step,
            "y_step": y_step,
            "homogeneous_check": homogeneous_check,
        },
        {
            "verdict": "exact",
            "x": "exact",
            "y": "exact",
            "solution_check": "exact",
            "x_step": "exact",
            "y_step": "exact",
        },
        _BASE_NON_CLAIMS
        + [
            "a*x + b*y = c and a*x_step + b*y_step = 0 are kernel-checked; the family (x + k*x_step, y + k*y_step) follows by linearity",
        ],
    )


def _pell_tool(arguments: dict) -> dict:
    d_token, d_value = _int_arg(
        arguments,
        "d",
        "d",
        allow_negative=False,
        allow_zero=False,
        max_digits=MAX_PELL_D_DIGITS,
    )
    if d_value < 2:
        raise Refusal("pell-domain", "d must be at least 2")
    root = math.isqrt(d_value)
    if root * root == d_value:
        square_check = _require_zero(
            f"(({root})*({root}))-({d_token})", "square degeneracy"
        )
        return _result(
            "nt-pell-exact-delegated-v1",
            {"d": d_token},
            {
                "verdict": "d-is-square",
                "root": str(root),
                "square_check": square_check,
            },
            {"verdict": "exact", "root": "exact"},
            _BASE_NON_CLAIMS
            + [
                "d = root^2 is kernel-checked; x^2 - d*y^2 = 1 then factors over the integers and admits no solution with y >= 1",
            ],
        )
    low_gap = _require_positive(
        f"({d_token})-(({root})*({root}))", "nonsquare lower gap"
    )
    high_gap = _require_positive(
        f"((({root})+1)*(({root})+1))-({d_token})", "nonsquare upper gap"
    )
    x_value, y_value, period = _pell_continued_fraction(d_value, root)
    x_token = str(x_value)
    y_token = str(y_value)
    if len(x_token) > MAX_PELL_SOLUTION_DIGITS:
        raise Refusal(
            "pell-budget", "the fundamental solution exceeds the digit budget"
        )
    identity_check = _require_zero(
        f"((({x_token})*({x_token}))-(({d_token})*({y_token})*({y_token})))-1",
        "Pell identity",
    )
    fields: dict = {
        "verdict": "fundamental-solution",
        "x": x_token,
        "y": y_token,
        "identity_check": identity_check,
        "period_length": str(period),
        "nonsquare_low_gap": low_gap,
        "nonsquare_high_gap": high_gap,
    }
    field_status = {
        "x": "exact",
        "y": "exact",
        "identity_check": "exact",
        "fundamental": "checked",
    }
    non_claims = list(_BASE_NON_CLAIMS)
    if y_value <= PELL_EXHAUSTIVE_MINIMALITY_LIMIT:
        for smaller in range(1, y_value):
            candidate = 1 + d_value * smaller * smaller
            candidate_root = math.isqrt(candidate)
            if candidate_root * candidate_root == candidate:
                raise Refusal("nt-internal", "a smaller Pell solution exists")
            _require_positive(
                f"(1+(({d_token})*({smaller})*({smaller})))-(({candidate_root})*({candidate_root}))",
                "minimality lower gap",
            )
            _require_positive(
                f"((({candidate_root})+1)*(({candidate_root})+1))-(1+(({d_token})*({smaller})*({smaller})))",
                "minimality upper gap",
            )
        fields["minimality"] = "exhaustively-verified"
        field_status["fundamental"] = "exact"
        non_claims.append(
            "Minimality was verified exhaustively: for every smaller y >= 1 the kernel checked that 1 + d*y^2 lies strictly between consecutive squares"
        )
    else:
        fields["minimality"] = "cf-derived"
        non_claims.append(
            "Fundamentality follows from the continued-fraction construction; the Pell identity is kernel-checked, minimality is not independently certified"
        )
    return _result(
        "nt-pell-exact-delegated-v1",
        {"d": d_token},
        fields,
        field_status,
        non_claims,
    )


def _mod_obstruction_tool(arguments: dict) -> dict:
    expression = arguments.get("expression")
    if (
        not isinstance(expression, str)
        or not expression
        or len(expression.encode("utf-8")) > MAX_EXPRESSION_BYTES
        or OBSTRUCTION_EXPRESSION.fullmatch(expression) is None
    ):
        raise Refusal(
            "obstruction-fragment",
            "expression must be a bounded integer polynomial in x (and optionally y) without division",
        )
    m_token, m_value = _int_arg(
        arguments, "modulus", "modulus", allow_negative=False, allow_zero=False
    )
    if m_value < 2 or m_value > MAX_OBSTRUCTION_MODULUS:
        raise Refusal(
            "obstruction-budget",
            f"modulus must be between 2 and {MAX_OBSTRUCTION_MODULUS}",
        )
    variables = arguments.get("variables", "x")
    if variables not in {"x", "x,y"}:
        raise Refusal("args", "variables must be 'x' or 'x,y'")
    uses_y = variables == "x,y"
    if Y_TOKEN.search(expression) and not uses_y:
        raise Refusal(
            "obstruction-fragment",
            "expression mentions y but variables does not declare it",
        )
    combinations = m_value * m_value if uses_y else m_value
    if combinations > MAX_OBSTRUCTION_CHECKS:
        raise Refusal(
            "obstruction-budget",
            f"the residue scan needs {combinations} kernel-decided classes; the budget is {MAX_OBSTRUCTION_CHECKS}",
        )
    residue_table: list[dict] = []
    witness: dict | None = None
    assignments = (
        ((x, y) for x in range(m_value) for y in range(m_value))
        if uses_y
        else ((x, None) for x in range(m_value))
    )
    for x_residue, y_residue in assignments:
        substituted = X_TOKEN.sub(f"({x_residue})", expression)
        if uses_y:
            substituted = Y_TOKEN.sub(f"({y_residue})", substituted)
        value, _ = _exact_int(substituted, "polynomial value")
        divisible, _ = _kernel_divides(m_token, value)
        row: dict = {"x": str(x_residue), "value": value, "divisible": "true" if divisible else "false"}
        if uses_y:
            row["y"] = str(y_residue)
        residue_table.append(row)
        if divisible and witness is None:
            witness = row
            break
    if witness is not None:
        return _result(
            "nt-mod-obstruction-exact-delegated-v1",
            {"expression": expression, "modulus": m_token, "variables": variables},
            {
                "verdict": "no-obstruction",
                "witness": witness,
                "classes_checked": str(len(residue_table)),
            },
            {"verdict": "exact", "witness": "exact"},
            _BASE_NON_CLAIMS
            + [
                "A residue class with kernel-verified divisibility exists, so no obstruction modulo this modulus; nothing is claimed about integer solvability",
            ],
        )
    return _result(
        "nt-mod-obstruction-exact-delegated-v1",
        {"expression": expression, "modulus": m_token, "variables": variables},
        {
            "verdict": "obstruction",
            "classes_checked": str(len(residue_table)),
            "residue_table": residue_table,
        },
        {"verdict": "exact", "residue_table": "exact"},
        _BASE_NON_CLAIMS
        + [
            "Every residue class was decided by the sealed runtime (value and non-divisibility); none was sampled or trusted to local arithmetic",
            "The step from the exhaustive residue obstruction to integer insolvability uses the reduction-mod-m rule for polynomial equations",
        ],
    )


def _vieta_descent_tool(arguments: dict) -> dict:
    a_token, a_value = _int_arg(
        arguments, "a", "a", allow_negative=False, allow_zero=False
    )
    b_token, b_value = _int_arg(
        arguments, "b", "b", allow_negative=False, allow_zero=False
    )
    numerator, _ = _exact_int(
        f"(({a_token})*({a_token}))+(({b_token})*({b_token}))", "a^2+b^2"
    )
    denominator, _ = _exact_int(f"(({a_token})*({b_token}))+1", "a*b+1"
    )
    divisible, _ = _kernel_divides(denominator, numerator)
    if not divisible:
        return _result(
            "nt-vieta-descent-exact-delegated-v1",
            {"a": a_token, "b": b_token},
            {
                "verdict": "not-a-solution",
                "numerator": numerator,
                "denominator": denominator,
                "denominator_divides_numerator": "false",
            },
            {"verdict": "exact"},
            _BASE_NON_CLAIMS
            + [
                "a*b+1 does not divide a^2+b^2 by sealed-runtime verdict, so the pair is outside the IMO 1988 P6 hypothesis; no descent applies",
            ],
        )
    k_token, k_value = _exact_int(f"({numerator})/({denominator})", "quotient k")
    state_a, state_b = (a_value, b_value) if a_value >= b_value else (b_value, a_value)
    chain: list[dict] = []

    def _verify_invariant(first: int, second: int) -> str:
        return _require_zero(
            f"((({first})*({first}))+(({second})*({second})))"
            f"-(({k_token})*(((({first})*({second}))+1)))",
            "descent state invariant",
        )

    _verify_invariant(state_a, state_b)
    steps = 0
    while state_b > 0:
        steps += 1
        if steps > MAX_DESCENT_STEPS:
            raise Refusal("descent-budget", "the descent chain exceeds the step budget")
        companion_token, companion = _exact_int(
            f"(({k_token})*({state_b}))-({state_a})", "companion root"
        )
        product_check = _require_zero(
            f"(({state_a})*({companion_token}))"
            f"-((({state_b})*({state_b}))-({k_token}))",
            "Vieta product identity",
        )
        if companion < 0:
            raise Refusal("nt-internal", "the companion root is negative")
        if companion >= state_b:
            raise Refusal("nt-internal", "the descent did not strictly decrease")
        if companion > 0:
            _require_positive(
                f"({state_b})-({companion_token})", "strict descent gap"
            )
        invariant_check = _verify_invariant(state_b, companion)
        chain.append(
            {
                "from": [str(state_a), str(state_b)],
                "companion": companion_token,
                "product_check": product_check,
                "invariant_check": invariant_check,
            }
        )
        state_a, state_b = state_b, companion
    square_check = _require_zero(
        f"(({state_a})*({state_a}))-({k_token})", "terminal square identity"
    )
    return _result(
        "nt-vieta-descent-exact-delegated-v1",
        {"a": a_token, "b": b_token},
        {
            "verdict": "quotient-is-square",
            "k": k_token,
            "square_root": str(state_a),
            "square_check": square_check,
            "descent_chain": chain,
            "chain_length": str(len(chain)),
        },
        {
            "verdict": "exact",
            "k": "exact",
            "square_root": "exact",
            "descent_chain": "exact",
        },
        _BASE_NON_CLAIMS
        + [
            "Every descent state satisfies A^2+B^2 = k*(A*B+1) by kernel check, every companion root satisfies the Vieta product identity, and the terminal state proves k = square_root^2",
            "This certifies the supplied instance and each state in its chain; the universal IMO 1988 P6 theorem is a proof schema, not claimed by one descent",
        ],
    )


def dispatch_integrated(
    name: str,
    arguments: dict,
    kernel_call: Callable[[str, dict], dict],
    identity: str,
) -> dict:
    global _KERNEL, _IDENTITY, _TRACE
    if name not in NUMBER_THEORY_TOOL_NAMES or not isinstance(arguments, dict):
        return {
            "status": "refused",
            "reason": "tool-unknown",
            "detail": "number-theory tool name or arguments are invalid",
        }

    class Kernel:
        @staticmethod
        def call(tool: str, delegated_arguments: dict) -> dict:
            return kernel_call(tool, delegated_arguments)

    _KERNEL = Kernel()
    _IDENTITY = identity
    _TRACE = []
    try:
        if name == "jackal_nt_factor":
            return _factor_tool(arguments)
        if name == "jackal_nt_lcm":
            return _lcm_tool(arguments)
        if name == "jackal_nt_valuation":
            return _valuation_tool(arguments)
        if name == "jackal_nt_is_square":
            return _is_square_tool(arguments)
        if name == "jackal_nt_congruence":
            return _congruence_tool(arguments)
        if name == "jackal_nt_sqrt_mod":
            return _sqrt_mod_tool(arguments)
        if name == "jackal_nt_linear_diophantine":
            return _linear_diophantine_tool(arguments)
        if name == "jackal_nt_pell":
            return _pell_tool(arguments)
        if name == "jackal_nt_mod_obstruction":
            return _mod_obstruction_tool(arguments)
        return _vieta_descent_tool(arguments)
    except Refusal as error:
        return _refusal(error.reason, error.detail)
    except Exception:
        return _refusal("nt-error", "number-theory orchestration failed closed")
    finally:
        _KERNEL = None
        _IDENTITY = None
        _TRACE = []


def _schema(properties: dict, required: list[str]) -> dict:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _definition(name: str, title: str, description: str, schema: dict) -> dict:
    return {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": schema,
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }


def _integer_property(description: str) -> dict:
    return {"type": "string", "description": description}


def tool_definitions() -> list[dict]:
    return [
        _definition(
            "jackal_nt_factor",
            "JACKAL certified factorization",
            "Certified prime factorization of a nonzero integer. Untrusted discovery (trial division, Pollard rho) proposes; the sealed runtime certifies every prime factor (Pratt) and kernel-checks the recomposition identity n = sign * prod(p^e). Refuses on budget instead of guessing.",
            _schema(
                {"n": _integer_property("Canonical nonzero integer to factor.")},
                ["n"],
            ),
        ),
        _definition(
            "jackal_nt_lcm",
            "JACKAL certified lcm",
            "Least common multiple with the sealed runtime's Bezout gcd certificate, a kernel-checked gcd*lcm = |a*b| identity, and kernel divisibility verdicts a | lcm and b | lcm.",
            _schema(
                {
                    "a": _integer_property("Canonical integer."),
                    "b": _integer_property("Canonical integer."),
                },
                ["a", "b"],
            ),
        ),
        _definition(
            "jackal_nt_valuation",
            "JACKAL certified p-adic valuation",
            "The p-adic valuation v_p(n) as a structured object: p is prime by sealed certificate, n = p^v * cofactor by kernel-exact division, and p does not divide the cofactor by kernel verdict.",
            _schema(
                {
                    "n": _integer_property("Canonical nonzero integer."),
                    "p": _integer_property("Prime whose valuation is taken (certified by the sealed runtime)."),
                },
                ["n", "p"],
            ),
        ),
        _definition(
            "jackal_nt_is_square",
            "JACKAL certified square decision",
            "Decides whether an integer is a perfect square with a kernel-checked witness: either root^2 = n, or the strict sandwich floor_root^2 < n < (floor_root+1)^2 between consecutive squares.",
            _schema(
                {"n": _integer_property("Canonical integer to test.")},
                ["n"],
            ),
        ),
        _definition(
            "jackal_nt_congruence",
            "JACKAL certified congruence",
            "Decides a = b (mod m) as a structured congruence object: the verdict is the sealed runtime's divisibility decision on a-b, and both canonical residues are kernel-verified to be congruent and in range.",
            _schema(
                {
                    "a": _integer_property("Canonical integer."),
                    "b": _integer_property("Canonical integer."),
                    "modulus": _integer_property("Positive modulus."),
                },
                ["a", "b", "modulus"],
            ),
        ),
        _definition(
            "jackal_nt_sqrt_mod",
            "JACKAL certified modular square root",
            "Square roots modulo a certified prime. Tonelli-Shanks is only the untrusted discovery path: each returned root carries a sealed-runtime r^2 = a (mod p) certificate, and non-residues carry a kernel-certified Euler criterion witness.",
            _schema(
                {
                    "a": _integer_property("Canonical integer whose root is sought."),
                    "p": _integer_property("Prime modulus (certified by the sealed runtime)."),
                },
                ["a", "p"],
            ),
        ),
        _definition(
            "jackal_nt_linear_diophantine",
            "JACKAL certified linear Diophantine solver",
            "Solves a*x + b*y = c over the integers with the sealed runtime's Bezout certificate: either a kernel-checked particular solution plus a kernel-checked homogeneous step describing the full family, or a kernel-verified gcd obstruction proving insolvability.",
            _schema(
                {
                    "a": _integer_property("Canonical integer coefficient."),
                    "b": _integer_property("Canonical integer coefficient."),
                    "c": _integer_property("Canonical integer target."),
                },
                ["a", "b", "c"],
            ),
        ),
        _definition(
            "jackal_nt_pell",
            "JACKAL certified Pell solver",
            "Fundamental solution of x^2 - d*y^2 = 1 for nonsquare d. Continued fractions are only the untrusted discovery path: the Pell identity, d's nonsquare sandwich, and (for small y) exhaustive minimality are kernel-checked. Fundamentality is otherwise labeled checked, never silently exact.",
            _schema(
                {"d": _integer_property("Positive nonsquare integer within the tool budget.")},
                ["d"],
            ),
        ),
        _definition(
            "jackal_nt_mod_obstruction",
            "JACKAL modular obstruction certificate",
            "Exhaustively decides a polynomial congruence P = 0 (mod m) over all residue classes in x (or x and y). Every class value and divisibility verdict comes from the sealed runtime, yielding either a verified obstruction certificate or a verified solvable witness.",
            _schema(
                {
                    "expression": {
                        "type": "string",
                        "description": "Integer polynomial in x (and optionally y) using + - * ^ and parentheses; no division.",
                    },
                    "modulus": _integer_property("Modulus between 2 and the tool budget."),
                    "variables": {
                        "type": "string",
                        "enum": ["x", "x,y"],
                        "description": "Variables scanned over residue classes (default x).",
                    },
                },
                ["expression", "modulus"],
            ),
        ),
        _definition(
            "jackal_nt_vieta_descent",
            "JACKAL Vieta-jumping descent",
            "IMO 1988 Problem 6 proof schema: for positive integers with (a*b+1) | (a^2+b^2), builds the full Vieta-jumping descent chain down to the terminal square, kernel-checking the quotient, every companion root, every Vieta product identity, every state invariant, and the terminal k = root^2. Non-solutions are decided by kernel divisibility.",
            _schema(
                {
                    "a": _integer_property("Positive canonical integer."),
                    "b": _integer_property("Positive canonical integer."),
                },
                ["a", "b"],
            ),
        ),
    ]


if __name__ == "__main__":
    raise SystemExit(
        "numbertheory.py is an identity-pinned JACKAL module, not a standalone service"
    )
