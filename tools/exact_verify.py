#!/usr/bin/env python3
"""JACKAL independent verifier for `jackal-exact-cert-v1` certificates.

This file OWNS the in-repo schema definition for the exact-lane
certificates (the way formal_receipt.py owns the receipt schema).  The
engine emits certificates as its final stdout line:

    exact-cert={"claim":{...},"kind":"<kind>","schema":"jackal-exact-cert-v1","witness":{...}}

and this verifier independently recomputes every claimed fact from the
certificate alone.  It never imports, imitates, or trusts engine code.

NORMATIVE SCHEMA SUMMARY (jackal-exact-cert-v1)
  * One JSON object; top-level keys EXACTLY {claim, kind, schema, witness};
    schema == "jackal-exact-cert-v1".  All numbers are decimal STRINGS
    (bare JSON numbers anywhere => REJECT `cert-schema`); rationals are
    canonical "p/q" with q >= 2 and gcd(p,q) == 1, or a plain integer
    string ("3", never "3/1"); integers have no '+', no leading zeros
    (except "0" itself), "-0" is malformed; <= 4096 digits (`int-budget`).
  * Kinds and their claim/witness fields, each fully recomputed here:
      xgcd           claim {a,b,g}                 witness {u,v}
      mod-inv        claim {a,m,inv}               witness {}
      mod-pow        claim {base,exp,mod,r}        witness {}
      crt            claim {residues[2..16],x,M}   witness {}
      prime          claim {n}                     witness Pratt node
                     {a, factors:[{q,e,cert:<node|null>}, ...]}
                     (depth <= 64, total nodes <= 512 => `pratt-budget`;
                      null subcert for q > 2 => `pratt-missing-subcert`)
      composite      claim {n}                     witness {divisor}
      poly-canon     claim {expr,degree,coeffs}    witness {}
      poly-eq        claim {lhs,rhs,equal}         witness {lhs_coeffs,rhs_coeffs}
      poly-gcd       claim {lhs,rhs,gcd_coeffs}    witness {}
      ratfunc-canon  claim {expr,num_coeffs,den_coeffs,
                            side_condition=="denominator-nonzero"} witness {}
      roots-isolate  claim {expr,distinct_real_roots,intervals}   witness {}
  * Expression fragment (own recursive-descent parser): tokens are
    nonneg decimal literals ("0", "12", "3.5", "1e3"; leading digit
    required), the single variable `x`, `+ - * / ^`, parentheses.
    Precedence: `^` right-associative and tighter than unary minus
    (-3^2 == -9); then `* /`; then binary `+ -`.  `^` exponents must be
    literal, nonnegative, integer-valued, and <= 64 (chained `a^b^c` has
    no literal exponent and is rejected).  Decimal literals become exact
    rationals.  POLY fragment: `/` divisor must be a nonzero CONSTANT
    subexpression.  RATFUNC fragment: `/` is unrestricted except the
    zero polynomial (`ratfunc-zero-den`).  Degree cap 64 after
    expansion and coefficient numerator/denominator cap 4096 decimal
    digits (`poly-budget`).
  * Output: `exact-verify=ACCEPT kind=<kind> cert_sha256=<hex>
    method=independent-recompute` (exit 0) or `exact-verify=REJECT
    reason=<class>` (exit 1, detail on stderr).  Reason classes are the
    stable strings in REASON_CLASSES below.  Exit 126 without
    interpreter isolation; exit 2 on CLI misuse.

These certificates back `status=exact` lanes only; there is no Lean
checker involvement and this verifier makes no claim beyond its own
independent recomputation of the statements above.
"""
from __future__ import annotations

import sys

if not (sys.flags.isolated and sys.flags.no_site):
    print(
        "exact_verify.py: refusing to run without interpreter isolation; "
        "invoke as: python3 -I -S -B tools/exact_verify.py <cert-file|->",
        file=sys.stderr,
    )
    raise SystemExit(126)

import hashlib  # noqa: E402
import json  # noqa: E402
from fractions import Fraction  # noqa: E402

SCHEMA = "jackal-exact-cert-v1"
MAX_CERT_BYTES = 4 * 1024 * 1024
MAX_INT_DIGITS = 4096
MAX_EXPR_BYTES = 1 << 20
MAX_POLY_DEGREE = 64
MAX_POW_EXPONENT = 64
MAX_LITERAL_EXP10 = 8192
PRATT_MAX_DEPTH = 64
PRATT_MAX_NODES = 512
CRT_MIN_RESIDUES = 2
CRT_MAX_RESIDUES = 16
SIDE_CONDITION = "denominator-nonzero"

_TEN_POW_CAP = 10 ** MAX_INT_DIGITS
_DIGITS = frozenset("0123456789")
_ZERO = Fraction(0)
_ONE = Fraction(1)

# Every REJECT reason this verifier can emit.  Stable strings.
REASON_CLASSES = (
    "cert-json",            # unreadable/oversized/duplicate-key/NaN/UTF-8/JSON-malformed input
    "cert-schema",          # envelope, field-set, type, count, or fixed-string violations
    "int-malformed",        # integer string not in canonical decimal form
    "int-budget",           # integer (or literal) beyond the 4096-digit cap
    "rat-not-canonical",    # rational string not gcd-reduced with denominator >= 2
    "poly-fragment",        # expression outside the poly/ratfunc grammar fragment
    "poly-budget",          # degree > 64 or coefficient digits > 4096 or oversized expr
    "ratfunc-zero-den",     # division by the zero polynomial in the ratfunc fragment
    "pratt-missing-subcert",  # q > 2 with a null Pratt subcertificate
    "pratt-budget",         # Pratt depth > 64 or total nodes > 512
    "xgcd-invalid",
    "mod-inv-invalid",
    "mod-pow-invalid",
    "crt-invalid",
    "prime-invalid",
    "composite-invalid",
    "poly-canon-mismatch",
    "poly-eq-mismatch",
    "poly-gcd-mismatch",
    "ratfunc-canon-mismatch",
    "roots-invalid",
    "verifier-internal",    # unexpected internal failure; always fail-closed
)


class Reject(Exception):
    """A named, fail-closed refusal."""

    def __init__(self, cls: str, detail: str = ""):
        super().__init__(f"{cls}: {detail}")
        self.cls = cls
        self.detail = detail


# ---------------------------------------------------------------------------
# Strict JSON loading
# ---------------------------------------------------------------------------

class _BareNumber(Exception):
    pass


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ValueError(f"non-standard JSON constant: {value}")


def _reject_bare_number(value):
    raise _BareNumber(value)


def load_cert(raw: bytes):
    if not isinstance(raw, bytes):
        raise Reject("cert-json", "input is not bytes")
    if len(raw) > MAX_CERT_BYTES:
        raise Reject("cert-json", f"certificate exceeds {MAX_CERT_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Reject("cert-json", f"not UTF-8: {exc}") from exc
    try:
        doc = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
            parse_int=_reject_bare_number,
            parse_float=_reject_bare_number,
        )
    except _BareNumber as exc:
        raise Reject("cert-schema", f"bare JSON number {exc}; all numbers must be strings") from exc
    except (ValueError, RecursionError) as exc:
        raise Reject("cert-json", str(exc)) from exc
    return doc


# ---------------------------------------------------------------------------
# Canonical integer / rational string parsing
# ---------------------------------------------------------------------------

def parse_int(s, what: str = "integer") -> int:
    if not isinstance(s, str) or not s:
        raise Reject("int-malformed", f"{what}: not a nonempty string")
    body = s[1:] if s[0] == "-" else s
    if not body or any(c not in _DIGITS for c in body):
        raise Reject("int-malformed", f"{what}: {s!r}")
    if len(body) > 1 and body[0] == "0":
        raise Reject("int-malformed", f"{what}: leading zero in {s!r}")
    if s[0] == "-" and body == "0":
        raise Reject("int-malformed", f"{what}: negative zero")
    if len(body) > MAX_INT_DIGITS:
        raise Reject("int-budget", f"{what}: {len(body)} digits > {MAX_INT_DIGITS}")
    value = int(body)
    return -value if s[0] == "-" else value


def parse_rat(s, what: str = "rational") -> Fraction:
    if not isinstance(s, str):
        raise Reject("int-malformed", f"{what}: not a string")
    if "/" not in s:
        return Fraction(parse_int(s, what))
    p_str, sep, q_str = s.partition("/")
    if "/" in q_str:
        raise Reject("rat-not-canonical", f"{what}: {s!r}")
    p = parse_int(p_str, what)
    q = parse_int(q_str, what)
    if q < 2:
        raise Reject("rat-not-canonical", f"{what}: denominator < 2 in {s!r}")
    frac = Fraction(p, q)
    if frac.numerator != p or frac.denominator != q:
        raise Reject("rat-not-canonical", f"{what}: {s!r} is not gcd-reduced")
    return frac


def rat_str(f: Fraction) -> str:
    if f.denominator == 1:
        return str(f.numerator)
    return f"{f.numerator}/{f.denominator}"


def _igcd(a: int, b: int) -> int:
    a, b = abs(a), abs(b)
    while b:
        a, b = b, a % b
    return a


# ---------------------------------------------------------------------------
# Dense polynomial arithmetic over Fraction (ascending coefficients;
# [] is the zero polynomial)
# ---------------------------------------------------------------------------

def _coeff_guard(c: Fraction) -> None:
    if abs(c.numerator) >= _TEN_POW_CAP or c.denominator >= _TEN_POW_CAP:
        raise Reject("poly-budget", "coefficient beyond the 4096-digit cap")


def pnorm(p):
    while p and p[-1] == 0:
        p.pop()
    for c in p:
        _coeff_guard(c)
    return p


def padd(a, b):
    n = max(len(a), len(b))
    out = [_ZERO] * n
    for i, c in enumerate(a):
        out[i] += c
    for i, c in enumerate(b):
        out[i] += c
    return pnorm(out)


def pneg(a):
    return [-c for c in a]


def psub(a, b):
    return padd(a, pneg(b))


def pmul(a, b):
    if not a or not b:
        return []
    out = [_ZERO] * (len(a) + len(b) - 1)
    for i, ca in enumerate(a):
        if ca == 0:
            continue
        for j, cb in enumerate(b):
            out[i + j] += ca * cb
    return pnorm(out)


def pscale(a, k: Fraction):
    if k == 0:
        return []
    return pnorm([c * k for c in a])


def pdivmod(a, b):
    if not b:
        raise Reject("verifier-internal", "division by zero polynomial")
    r = list(a)
    db = len(b) - 1
    lb = b[-1]
    q = [_ZERO] * max(len(a) - db, 0)
    while r and len(r) - 1 >= db:
        shift = len(r) - 1 - db
        c = r[-1] / lb
        q[shift] = c
        for i, cb in enumerate(b):
            r[shift + i] -= c * cb
        while r and r[-1] == 0:
            r.pop()
    return pnorm(q), pnorm(r)


def pmonic(p):
    if not p:
        return []
    lc = p[-1]
    if lc == 1:
        return list(p)
    return pnorm([c / lc for c in p])


def pgcd(a, b):
    a, b = list(a), list(b)
    while b:
        a, b = b, pdivmod(a, b)[1]
    return pmonic(a)


def pderiv(p):
    return pnorm([p[i] * i for i in range(1, len(p))])


def peval(p, t: Fraction) -> Fraction:
    acc = _ZERO
    for c in reversed(p):
        acc = acc * t + c
    return acc


def sturm_chain(s):
    chain = [list(s)]
    nxt = pderiv(s)
    while nxt:
        chain.append(nxt)
        rem = pdivmod(chain[-2], chain[-1])[1]
        nxt = pneg(rem)
    return chain


def sign_variations(chain, t: Fraction) -> int:
    signs = []
    for p in chain:
        v = peval(p, t)
        if v != 0:
            signs.append(1 if v > 0 else -1)
    return sum(1 for i in range(1, len(signs)) if signs[i] != signs[i - 1])


# ---------------------------------------------------------------------------
# Expression fragment: tokenizer + recursive-descent parser
# Values are (num, den) pairs of dense polynomials; den is [1] in the
# poly fragment and monic/coprime after every ratfunc normalization.
# ---------------------------------------------------------------------------

def _tokenize(src: str):
    toks = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in " \t":
            i += 1
            continue
        if c in "+-*/^()":
            toks.append((c, None))
            i += 1
            continue
        if c == "x":
            toks.append(("var", None))
            i += 1
            continue
        if c in _DIGITS:
            j = i
            while j < n and src[j] in _DIGITS:
                j += 1
            int_part = src[i:j]
            frac_part = ""
            if j < n and src[j] == ".":
                j += 1
                k = j
                while j < n and src[j] in _DIGITS:
                    j += 1
                if j == k:
                    raise Reject("poly-fragment", "digits required after decimal point")
                frac_part = src[k:j]
            exp10 = 0
            if j < n and src[j] in "eE":
                j += 1
                sign = 1
                if j < n and src[j] in "+-":
                    sign = -1 if src[j] == "-" else 1
                    j += 1
                k = j
                while j < n and src[j] in _DIGITS:
                    j += 1
                if j == k:
                    raise Reject("poly-fragment", "digits required in exponent part")
                if j - k > 5 or int(src[k:j]) > MAX_LITERAL_EXP10:
                    raise Reject("int-budget", "literal power-of-ten exponent too large")
                exp10 = sign * int(src[k:j])
            if len(int_part) + len(frac_part) > MAX_INT_DIGITS:
                raise Reject("int-budget", "literal mantissa beyond the 4096-digit cap")
            value = Fraction(int(int_part + frac_part), 10 ** len(frac_part))
            if exp10 >= 0:
                value *= 10 ** exp10
            else:
                value /= 10 ** (-exp10)
            is_plain_int = not frac_part and exp10 == 0
            toks.append(("num", (value, is_plain_int)))
            i = j
            continue
        raise Reject("poly-fragment", f"unexpected character {c!r}")
    return toks


class _ExprParser:
    def __init__(self, toks, mode: str):
        self.toks = toks
        self.pos = 0
        self.mode = mode  # "poly" or "ratfunc"

    def _peek(self):
        if self.pos < len(self.toks):
            return self.toks[self.pos][0]
        return None

    def _take(self):
        tok = self.toks[self.pos]
        self.pos += 1
        return tok

    # -- value helpers ------------------------------------------------
    def _norm(self, num, den):
        num, den = pnorm(num), pnorm(den)
        if not den:
            raise Reject("verifier-internal", "zero denominator escaped division guard")
        if not num:
            den = [_ONE]
        else:
            g = pgcd(num, den)
            if len(g) > 1 or g[0] != 1:
                num = pdivmod(num, g)[0]
                den = pdivmod(den, g)[0]
            lc = den[-1]
            if lc != 1:
                num = [c / lc for c in num]
                den = [c / lc for c in den]
        if len(num) - 1 > MAX_POLY_DEGREE or len(den) - 1 > MAX_POLY_DEGREE:
            raise Reject("poly-budget", f"degree beyond {MAX_POLY_DEGREE} after expansion")
        for c in num:
            _coeff_guard(c)
        for c in den:
            _coeff_guard(c)
        return num, den

    def _add(self, a, b):
        return self._norm(padd(pmul(a[0], b[1]), pmul(b[0], a[1])), pmul(a[1], b[1]))

    def _sub(self, a, b):
        return self._add(a, (pneg(b[0]), b[1]))

    def _mul(self, a, b):
        return self._norm(pmul(a[0], b[0]), pmul(a[1], b[1]))

    def _div(self, a, b):
        if self.mode == "poly":
            # divisor must be a nonzero constant subexpression
            if len(b[0]) > 1 or len(b[1]) > 1:
                raise Reject("poly-fragment", "poly fragment divisor must be constant")
            if not b[0]:
                raise Reject("poly-fragment", "poly fragment division by zero constant")
            return self._norm(pscale(a[0], _ONE / b[0][0]), a[1])
        if not b[0]:
            raise Reject("ratfunc-zero-den", "division by the zero polynomial")
        return self._norm(pmul(a[0], b[1]), pmul(a[1], b[0]))

    def _pow(self, base, e: int):
        result = ([_ONE], [_ONE])
        for _ in range(e):
            result = self._mul(result, base)
        return result

    # -- grammar ------------------------------------------------------
    def parse(self):
        value = self._expr()
        if self.pos != len(self.toks):
            raise Reject("poly-fragment", "trailing tokens after expression")
        return value

    def _expr(self):
        value = self._term()
        while self._peek() in ("+", "-"):
            op = self._take()[0]
            rhs = self._term()
            value = self._add(value, rhs) if op == "+" else self._sub(value, rhs)
        return value

    def _term(self):
        value = self._unary()
        while self._peek() in ("*", "/"):
            op = self._take()[0]
            rhs = self._unary()
            value = self._mul(value, rhs) if op == "*" else self._div(value, rhs)
        return value

    def _unary(self):
        if self._peek() == "-":
            self._take()
            num, den = self._unary()
            return (pneg(num), den)
        return self._power()

    def _power(self):
        base = self._atom()
        if self._peek() != "^":
            return base
        self._take()
        if self._peek() != "num":
            raise Reject("poly-fragment", "exponent must be a nonneg integer literal")
        value, _plain = self._take()[1]
        if value.denominator != 1 or value < 0:
            raise Reject("poly-fragment", "exponent must be a nonneg integer literal")
        if value > MAX_POW_EXPONENT:
            raise Reject("poly-budget", f"exponent beyond {MAX_POW_EXPONENT}")
        if self._peek() == "^":
            # right-associative ^ requires a literal exponent tower, which
            # the fragment cannot express: a^b^c has no literal exponent.
            raise Reject("poly-fragment", "chained ^ has no literal exponent")
        return self._pow(base, int(value))

    def _atom(self):
        kind = self._peek()
        if kind == "num":
            value, _plain = self._take()[1]
            return ([value] if value != 0 else [], [_ONE])
        if kind == "var":
            self._take()
            return ([_ZERO, _ONE], [_ONE])
        if kind == "(":
            self._take()
            value = self._expr()
            if self._peek() != ")":
                raise Reject("poly-fragment", "unbalanced parenthesis")
            self._take()
            return value
        raise Reject("poly-fragment", f"unexpected token {kind!r}")


def eval_expr(src, mode: str):
    if not isinstance(src, str):
        raise Reject("cert-schema", "expression must be a string")
    if len(src) > MAX_EXPR_BYTES:
        raise Reject("poly-budget", "expression too large")
    toks = _tokenize(src)
    if not toks:
        raise Reject("poly-fragment", "empty expression")
    return _ExprParser(toks, mode).parse()


def eval_poly(src):
    num, den = eval_expr(src, "poly")
    if len(den) != 1 or den[0] != 1:
        raise Reject("verifier-internal", "poly fragment produced a denominator")
    return num


def coeff_strings(p):
    if not p:
        return ["0"]
    return [rat_str(c) for c in p]


# ---------------------------------------------------------------------------
# Shared claim/witness plumbing
# ---------------------------------------------------------------------------

def _require_fields(obj, fields, where: str):
    if not isinstance(obj, dict):
        raise Reject("cert-schema", f"{where} must be a JSON object")
    if set(obj) != set(fields):
        raise Reject("cert-schema", f"{where} keys {sorted(obj)} != {sorted(fields)}")


def _rat_list(value, what: str):
    if not isinstance(value, list) or not value:
        raise Reject("cert-schema", f"{what} must be a nonempty array of strings")
    out = []
    for item in value:
        parse_rat(item, what)  # canonical-form enforcement
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Kind handlers — every check recomputed, nothing trusted
# ---------------------------------------------------------------------------

def _check_xgcd(claim, witness):
    _require_fields(claim, ("a", "b", "g"), "claim")
    _require_fields(witness, ("u", "v"), "witness")
    a = parse_int(claim["a"], "a")
    b = parse_int(claim["b"], "b")
    g = parse_int(claim["g"], "g")
    u = parse_int(witness["u"], "u")
    v = parse_int(witness["v"], "v")
    if g < 0:
        raise Reject("xgcd-invalid", "g must be nonnegative")
    if u * a + v * b != g:
        raise Reject("xgcd-invalid", "u*a + v*b != g")
    if g == 0:
        if a != 0 or b != 0:
            raise Reject("xgcd-invalid", "g == 0 requires a == b == 0")
    else:
        if a % g != 0 or b % g != 0:
            raise Reject("xgcd-invalid", "g does not divide both a and b")


def _check_mod_inv(claim, witness):
    _require_fields(claim, ("a", "m", "inv"), "claim")
    _require_fields(witness, (), "witness")
    a = parse_int(claim["a"], "a")
    m = parse_int(claim["m"], "m")
    inv = parse_int(claim["inv"], "inv")
    if m < 2:
        raise Reject("mod-inv-invalid", "m must be >= 2")
    if not 0 <= inv < m:
        raise Reject("mod-inv-invalid", "inv out of range [0, m)")
    if (a * inv) % m != 1:
        raise Reject("mod-inv-invalid", "(a * inv) % m != 1")


def _check_mod_pow(claim, witness):
    _require_fields(claim, ("base", "exp", "mod", "r"), "claim")
    _require_fields(witness, (), "witness")
    base = parse_int(claim["base"], "base")
    exp = parse_int(claim["exp"], "exp")
    mod = parse_int(claim["mod"], "mod")
    r = parse_int(claim["r"], "r")
    if exp < 0:
        raise Reject("mod-pow-invalid", "exp must be nonnegative")
    if mod < 1:
        raise Reject("mod-pow-invalid", "mod must be >= 1")
    if not 0 <= r < mod:
        raise Reject("mod-pow-invalid", "r out of range [0, mod)")
    if pow(base, exp, mod) != r:
        raise Reject("mod-pow-invalid", "pow(base, exp, mod) != r")


def _check_crt(claim, witness):
    _require_fields(claim, ("residues", "x", "M"), "claim")
    _require_fields(witness, (), "witness")
    residues = claim["residues"]
    if not isinstance(residues, list):
        raise Reject("cert-schema", "residues must be an array")
    if not CRT_MIN_RESIDUES <= len(residues) <= CRT_MAX_RESIDUES:
        raise Reject(
            "cert-schema",
            f"residue count {len(residues)} outside [{CRT_MIN_RESIDUES}, {CRT_MAX_RESIDUES}]",
        )
    pairs = []
    for item in residues:
        _require_fields(item, ("r", "m"), "residue")
        pairs.append((parse_int(item["r"], "r"), parse_int(item["m"], "m")))
    x = parse_int(claim["x"], "x")
    big_m = parse_int(claim["M"], "M")
    prod = 1
    for _, m in pairs:
        if m < 2:
            raise Reject("crt-invalid", "every modulus must be >= 2")
        prod *= m
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            if _igcd(pairs[i][1], pairs[j][1]) != 1:
                raise Reject("crt-invalid", "moduli are not pairwise coprime")
    if big_m != prod:
        raise Reject("crt-invalid", "M != product of moduli")
    if not 0 <= x < big_m:
        raise Reject("crt-invalid", "x out of range [0, M)")
    for r, m in pairs:
        if x % m != r % m:
            raise Reject("crt-invalid", "x does not match a claimed residue")


def _pratt_prepass(node, depth: int, state):
    if depth > PRATT_MAX_DEPTH:
        raise Reject("pratt-budget", f"Pratt depth beyond {PRATT_MAX_DEPTH}")
    state[0] += 1
    if state[0] > PRATT_MAX_NODES:
        raise Reject("pratt-budget", f"Pratt nodes beyond {PRATT_MAX_NODES}")
    if isinstance(node, dict):
        factors = node.get("factors")
        if isinstance(factors, list):
            for item in factors:
                if isinstance(item, dict):
                    cert = item.get("cert")
                    if cert is not None:
                        _pratt_prepass(cert, depth + 1, state)


def _pratt_verify(n: int, node):
    _require_fields(node, ("a", "factors"), "Pratt node")
    if n < 2:
        raise Reject("prime-invalid", "n must be >= 2")
    if n in (2, 3):
        parse_int(node["a"], "a")
        if not isinstance(node["factors"], list):
            raise Reject("cert-schema", "Pratt factors must be an array")
        return
    a = parse_int(node["a"], "a")
    factors = node["factors"]
    if not isinstance(factors, list) or not factors:
        raise Reject("prime-invalid", "n > 3 requires a nonempty factor list")
    qs = []
    prod = 1
    n_bits = n.bit_length()
    for item in factors:
        _require_fields(item, ("q", "e", "cert"), "Pratt factor")
        q = parse_int(item["q"], "q")
        e = parse_int(item["e"], "e")
        if q < 2:
            raise Reject("prime-invalid", "factor q must be >= 2")
        if e < 1:
            raise Reject("prime-invalid", "factor exponent must be >= 1")
        if e * (q.bit_length() - 1) > n_bits:
            raise Reject("prime-invalid", "q^e exceeds n-1")
        cert = item["cert"]
        if cert is None:
            if q != 2:
                raise Reject("pratt-missing-subcert", f"q={q} needs its own Pratt node")
        else:
            _pratt_verify(q, cert)
        qs.append(q)
        prod *= q ** e
    if len(set(qs)) != len(qs):
        raise Reject("prime-invalid", "factor primes must be distinct")
    if prod != n - 1:
        raise Reject("prime-invalid", "product of q^e != n-1")
    if not 2 <= a < n:
        raise Reject("prime-invalid", "witness a out of range [2, n)")
    if pow(a, n - 1, n) != 1:
        raise Reject("prime-invalid", "a^(n-1) % n != 1")
    for q in qs:
        if pow(a, (n - 1) // q, n) == 1:
            raise Reject("prime-invalid", f"a^((n-1)/{q}) % n == 1")


def _check_prime(claim, witness):
    _require_fields(claim, ("n",), "claim")
    n = parse_int(claim["n"], "n")
    _pratt_prepass(witness, 1, [0])
    _pratt_verify(n, witness)


def _check_composite(claim, witness):
    _require_fields(claim, ("n",), "claim")
    _require_fields(witness, ("divisor",), "witness")
    n = parse_int(claim["n"], "n")
    divisor = parse_int(witness["divisor"], "divisor")
    if not 1 < divisor < n:
        raise Reject("composite-invalid", "divisor out of range (1, n)")
    if n % divisor != 0:
        raise Reject("composite-invalid", "divisor does not divide n")


def _check_poly_canon(claim, witness):
    _require_fields(claim, ("expr", "degree", "coeffs"), "claim")
    _require_fields(witness, (), "witness")
    degree = claim["degree"]
    parse_int(degree, "degree")
    coeffs = _rat_list(claim["coeffs"], "coeffs")
    p = eval_poly(claim["expr"])
    want_coeffs = coeff_strings(p)
    want_degree = str(len(p) - 1) if p else "-1"
    if coeffs != want_coeffs or degree != want_degree:
        raise Reject("poly-canon-mismatch", "claimed canonical form differs from recomputation")


def _check_poly_eq(claim, witness):
    _require_fields(claim, ("lhs", "rhs", "equal"), "claim")
    _require_fields(witness, ("lhs_coeffs", "rhs_coeffs"), "witness")
    equal = claim["equal"]
    if not isinstance(equal, bool):
        raise Reject("cert-schema", "equal must be a JSON boolean")
    wl = _rat_list(witness["lhs_coeffs"], "lhs_coeffs")
    wr = _rat_list(witness["rhs_coeffs"], "rhs_coeffs")
    ls = coeff_strings(eval_poly(claim["lhs"]))
    rs = coeff_strings(eval_poly(claim["rhs"]))
    if wl != ls or wr != rs:
        raise Reject("poly-eq-mismatch", "witness coefficients differ from recomputation")
    if equal != (ls == rs):
        raise Reject("poly-eq-mismatch", "equal flag differs from recomputation")


def _check_poly_gcd(claim, witness):
    _require_fields(claim, ("lhs", "rhs", "gcd_coeffs"), "claim")
    _require_fields(witness, (), "witness")
    gcd_coeffs = _rat_list(claim["gcd_coeffs"], "gcd_coeffs")
    g = pgcd(eval_poly(claim["lhs"]), eval_poly(claim["rhs"]))
    if gcd_coeffs != coeff_strings(g):
        raise Reject("poly-gcd-mismatch", "claimed gcd differs from recomputation")


def _check_ratfunc_canon(claim, witness):
    _require_fields(
        claim, ("expr", "num_coeffs", "den_coeffs", "side_condition"), "claim"
    )
    _require_fields(witness, (), "witness")
    if claim["side_condition"] != SIDE_CONDITION:
        raise Reject("cert-schema", f"side_condition must be {SIDE_CONDITION!r}")
    num_coeffs = _rat_list(claim["num_coeffs"], "num_coeffs")
    den_coeffs = _rat_list(claim["den_coeffs"], "den_coeffs")
    num, den = eval_expr(claim["expr"], "ratfunc")
    if num_coeffs != coeff_strings(num) or den_coeffs != coeff_strings(den):
        raise Reject("ratfunc-canon-mismatch", "claimed canonical form differs from recomputation")


def _check_roots_isolate(claim, witness):
    _require_fields(claim, ("expr", "distinct_real_roots", "intervals"), "claim")
    _require_fields(witness, (), "witness")
    k = parse_int(claim["distinct_real_roots"], "distinct_real_roots")
    if k < 0:
        raise Reject("roots-invalid", "distinct_real_roots must be nonnegative")
    intervals = claim["intervals"]
    if not isinstance(intervals, list):
        raise Reject("cert-schema", "intervals must be an array")
    parsed = []
    for item in intervals:
        if not isinstance(item, list) or len(item) != 2:
            raise Reject("cert-schema", "each interval must be a 2-element array")
        parsed.append((parse_rat(item[0], "interval endpoint"),
                       parse_rat(item[1], "interval endpoint")))
    if len(parsed) != k:
        raise Reject("roots-invalid", "interval count differs from distinct_real_roots")
    p = eval_poly(claim["expr"])
    if not p:
        raise Reject("roots-invalid", "zero polynomial has no isolated root set")
    g = pgcd(p, pderiv(p))
    s = pmonic(pdivmod(p, g)[0])
    chain = sturm_chain(s)
    bound = _ONE + max((abs(c) for c in s[:-1]), default=_ZERO)
    total = sign_variations(chain, -bound) - sign_variations(chain, bound)
    if total != k:
        raise Reject("roots-invalid", "Sturm root count differs from distinct_real_roots")
    prev_b = None
    for a, b in parsed:
        if a > b:
            raise Reject("roots-invalid", "interval with a > b")
        if prev_b is not None and not prev_b < a:
            raise Reject("roots-invalid", "intervals not strictly increasing")
        if peval(s, a) == 0:
            raise Reject("roots-invalid", "left endpoint is a root")
        if sign_variations(chain, a) - sign_variations(chain, b) != 1:
            raise Reject("roots-invalid", "interval does not isolate exactly one root")
        prev_b = b


_HANDLERS = {
    "xgcd": _check_xgcd,
    "mod-inv": _check_mod_inv,
    "mod-pow": _check_mod_pow,
    "crt": _check_crt,
    "prime": _check_prime,
    "composite": _check_composite,
    "poly-canon": _check_poly_canon,
    "poly-eq": _check_poly_eq,
    "poly-gcd": _check_poly_gcd,
    "ratfunc-canon": _check_ratfunc_canon,
    "roots-isolate": _check_roots_isolate,
}


def verify_bytes(raw: bytes) -> tuple[str, str]:
    doc = load_cert(raw)
    if not isinstance(doc, dict):
        raise Reject("cert-schema", "certificate must be a JSON object")
    if set(doc) != {"claim", "kind", "schema", "witness"}:
        raise Reject("cert-schema", f"top-level keys {sorted(doc)}")
    if doc["schema"] != SCHEMA:
        raise Reject("cert-schema", f"schema {doc['schema']!r} != {SCHEMA!r}")
    kind = doc["kind"]
    if not isinstance(kind, str) or kind not in _HANDLERS:
        raise Reject("cert-schema", f"unknown kind {kind!r}")
    claim, witness = doc["claim"], doc["witness"]
    if not isinstance(claim, dict) or not isinstance(witness, dict):
        raise Reject("cert-schema", "claim and witness must be JSON objects")
    _HANDLERS[kind](claim, witness)
    return kind, hashlib.sha256(raw).hexdigest()


def main(argv) -> int:
    if len(argv) != 1:
        print("usage: python3 -I -S -B tools/exact_verify.py <cert-file|->", file=sys.stderr)
        return 2
    try:
        if argv[0] == "-":
            raw = sys.stdin.buffer.read(MAX_CERT_BYTES + 1)
        else:
            with open(argv[0], "rb") as fh:
                raw = fh.read(MAX_CERT_BYTES + 1)
    except OSError as exc:
        print("exact-verify=REJECT reason=cert-json")
        print(f"exact_verify: cert-json: unreadable input: {exc}", file=sys.stderr)
        return 1
    try:
        kind, digest = verify_bytes(raw)
    except Reject as refusal:
        print(f"exact-verify=REJECT reason={refusal.cls}")
        print(f"exact_verify: {refusal.cls}: {refusal.detail}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — fail closed, never accept on error
        print("exact-verify=REJECT reason=verifier-internal")
        print(f"exact_verify: verifier-internal: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"exact-verify=ACCEPT kind={kind} cert_sha256={digest} method=independent-recompute")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
