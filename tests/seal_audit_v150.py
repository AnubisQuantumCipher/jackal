#!/usr/bin/env python3
"""v1.5.0 post-gate seal audit: adversarial dogfood corpus (§audit-G).

Independent-of-the-suites probe battery over the exact CAS lanes, the
formal fragments, canonical serialization, branch boundaries, malformed
inputs, budgets, and tampering.  Every mathematical cross-check is
recomputed IN THIS FILE from first principles (Python ints/Fractions) —
verifier agreement alone is never treated as proof.  Writes a durable
evidence transcript to release/evidence/seal_audit_v150.json.

Run: python3 tests/seal_audit_v150.py            (uses ./jackal-native)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = os.environ.get("JACKAL_BIN") or str(ROOT / "jackal-native")
CHECKER = ROOT / "proofs/lean/.lake/build/bin/jackal_cert_check"
VERIFIER = ROOT / "tools/exact_verify.py"
EVIDENCE = ROOT / "release/evidence/seal_audit_v150.json"

ROWS: list[dict] = []


def run(*args: str, inp: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, input=inp, timeout=300)


def eng(*args: str) -> subprocess.CompletedProcess:
    return run(ENGINE, *args)


_VOLATILE_THREAD = re.compile(r"(thread '[^']*') \(\d+\)")
_VOLATILE_TMPDIR = re.compile(
    r"/(?:private/)?(?:var/folders/[^\s'\"]+|tmp/[A-Za-z0-9._-]*(?:tmp|-)[A-Za-z0-9._-]{4,})")


def scrub_volatile(text: str) -> str:
    """Strip host-volatile identifiers (thread ids, random temp paths) from
    durable evidence text while preserving the failure reason itself.

    Anubis panic banners embed a fresh thread id per process
    (``thread '<unnamed>' (117372970) panicked at src/main.rs:...``); the id
    changes on every run even when behavior is byte-identical, which made the
    shipped evidence transcript non-reproducible.  The panic message, source
    location, and return codes are all kept.
    """
    text = _VOLATILE_THREAD.sub(r"\1", text)
    return _VOLATILE_TMPDIR.sub("<tmpdir>", text)


def record(rid: str, ok: bool, expect: str, observed: str) -> None:
    observed = scrub_volatile(observed)
    ROWS.append({"id": rid, "ok": bool(ok), "expect": expect,
                 "observed": observed[:300]})
    print(f"{'PASS' if ok else 'FAIL'} {rid}" + ("" if ok else f" — {observed[:160]}"))


def cert_of(stdout: bytes) -> dict | None:
    for line in stdout.decode(errors="replace").splitlines():
        if line.startswith("exact-cert="):
            return json.loads(line[len("exact-cert="):])
    return None


def verify_cert(cert: dict) -> tuple[int, str]:
    raw = json.dumps(cert, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True).encode()
    p = run(sys.executable, "-I", "-S", "-B", str(VERIFIER), "-", inp=raw)
    return p.returncode, (p.stdout or p.stderr).decode(errors="replace").strip()


# ---------------------------------------------------------------- B: exact lanes
def audit_number_theory() -> None:
    # xgcd sign lattice + INDEPENDENT Bezout recomputation.
    for a, b in [("0", "0"), ("0", "5"), ("-5", "0"), ("240", "-46"),
                 ("-240", "-46"), ("1", "-1"),
                 (str(10**100 + 7), str(-(10**99 + 3)))]:
        p = eng("xgcd", a, b)
        if p.returncode != 0:
            record(f"xgcd({a[:8]},{b[:8]})", False, "exit0", p.stderr.decode()[:100])
            continue
        c = cert_of(p.stdout)
        g, u, v = int(c["claim"]["g"]), int(c["witness"]["u"]), int(c["witness"]["v"])
        ia, ib = int(a), int(b)
        ok = (u * ia + v * ib == g and g == math.gcd(ia, ib)
              and verify_cert(c)[0] == 0)
        record(f"xgcd({a[:8]},{b[:8]})", ok, "bezout+gcd+verify",
               f"g={g} u={u} v={v}")

    # Integer-token boundary behavior (AUDIT FINDING, documented residual):
    # digit-string leniency — `007` and `-0` are NORMALIZED at ingestion
    # (values 7 and 0) and every emitted certificate token is canonical, so
    # the independent verifier accepts and no wrong value or assurance
    # movement is possible.  Making the CLI refuse them would change accept
    # behavior (scope-frozen; needs sign-off).  The invariant asserted here
    # is the one that carries trust: canonical claims + correct value +
    # independent verification.  Genuinely malformed tokens must refuse.
    for tok, canon_val in [("007", "7"), ("-0", "0")]:
        p = eng("xgcd", tok, "3")
        c = cert_of(p.stdout) if p.returncode == 0 else None
        ok = (p.returncode == 0 and c is not None
              and c["claim"]["a"] == canon_val
              and int(c["witness"]["u"]) * int(canon_val)
              + int(c["witness"]["v"]) * 3 == int(c["claim"]["g"])
              and verify_cert(c)[0] == 0)
        record(f"xgcd-lenient-token({tok})", ok,
               f"normalized claim a={canon_val} + verify", json.dumps(c)[:120] if c else p.stderr.decode()[:80])
    for tok in ["+5", "abc", "5.0", "0x7"]:
        p = eng("xgcd", tok, "3")
        record(f"xgcd-malformed({tok})", p.returncode != 0, "refuse",
               f"rc={p.returncode} {p.stderr.decode()[:80]}")

    # mod-pow conventions + independent recomputation.
    for b, e, m, want in [("0", "0", "7", pow(0, 0, 7)), ("2", "0", "7", 1),
                          ("5", "117", "19", pow(5, 117, 19)),
                          ("2", "10000", "998244353", pow(2, 10000, 998244353)),
                          ("-3", "5", "7", pow(-3, 5, 7))]:
        p = eng("mod-pow", b, e, m)
        if p.returncode != 0:
            record(f"mod-pow({b},{e},{m})", False, "exit0", p.stderr.decode()[:100])
            continue
        c = cert_of(p.stdout)
        r = int(c["claim"]["r"])
        ok = r == want and verify_cert(c)[0] == 0
        record(f"mod-pow({b},{e},{m})", ok, f"r={want}", f"r={r}")

    # mod-pow m=1: everything is 0.
    p = eng("mod-pow", "5", "3", "1")
    c = cert_of(p.stdout) if p.returncode == 0 else None
    record("mod-pow-m1", p.returncode == 0 and c and int(c["claim"]["r"]) == 0,
           "r=0", p.stdout.decode()[:80] if p.returncode == 0 else p.stderr.decode()[:80])

    # mod-inv: coprime accept + independent check; non-coprime refuse; m<=1 refuse.
    p = eng("mod-inv", "17", "3120")
    c = cert_of(p.stdout)
    inv = int(c["claim"]["inv"])
    record("mod-inv(17,3120)", (17 * inv) % 3120 == 1 and verify_cert(c)[0] == 0,
           "a*inv%m==1", f"inv={inv}")
    for a, m in [("6", "9"), ("5", "1"), ("5", "0"), ("0", "7")]:
        p = eng("mod-inv", a, m)
        record(f"mod-inv-refuse({a},{m})", p.returncode != 0, "refuse",
               f"rc={p.returncode}")

    # CRT: independent congruence check; non-coprime refusal; count limits.
    p = eng("crt", "2", "3", "3", "5", "2", "7")
    c = cert_of(p.stdout)
    x, M = int(c["claim"]["x"]), int(c["claim"]["M"])
    ok = M == 105 and x % 3 == 2 and x % 5 == 3 and x % 7 == 2 and 0 <= x < M \
        and verify_cert(c)[0] == 0
    record("crt-3mod", ok, "congruences", f"x={x} M={M}")
    p = eng("crt", "1", "4", "2", "6")
    record("crt-noncoprime-refuse", p.returncode != 0, "refuse", f"rc={p.returncode}")

    # Pratt: known primes/composites incl. Carmichael + INDEPENDENT recursive check.
    def pratt_check(n: int, node: dict | None) -> bool:
        if n in (2, 3):
            return True
        if node is None:
            return False
        a = int(node["a"])
        prod = 1
        for f in node["factors"]:
            q, e = int(f["q"]), int(f["e"])
            prod *= q ** e
            if q == 2:
                pass
            elif not pratt_check(q, f["cert"]):
                return False
        if prod != n - 1 or pow(a, n - 1, n) != 1:
            return False
        return all(pow(a, (n - 1) // int(f["q"]), n) != 1 for f in node["factors"])

    for n in ["1000003", "2", "3", str(10**18 + 9)]:
        p = eng("prime-cert", n)
        c = cert_of(p.stdout)
        ok = (p.returncode == 0 and c["kind"] == "prime"
              and pratt_check(int(n), c["witness"]) and verify_cert(c)[0] == 0)
        record(f"pratt({n})", ok, "prime+independent-pratt", p.stdout.decode()[:60])
    for n in ["561", "1105", "41041", "4"]:
        p = eng("prime-cert", n)
        c = cert_of(p.stdout)
        d = int(c["witness"]["divisor"])
        ok = (c["kind"] == "composite" and 1 < d < int(n) and int(n) % d == 0
              and verify_cert(c)[0] == 0)
        record(f"composite({n})", ok, "divisor", f"d={d}")
    p = eng("prime-cert", "0")
    record("prime-cert-0-refuse", p.returncode != 0, "refuse", f"rc={p.returncode}")
    p = eng("prime-cert", "1")
    record("prime-cert-1-refuse", p.returncode != 0, "refuse", f"rc={p.returncode}")


def audit_polynomials() -> None:
    # Normalization idempotence: canonical coeffs reparse to themselves.
    p1 = eng("poly-canon", "(x+1)*(x-1)*(x+2)")
    c1 = cert_of(p1.stdout)
    coeffs = c1["claim"]["coeffs"]
    rebuilt = "+".join(f"({c})*x^{i}" for i, c in enumerate(coeffs)).replace("(", "(0+", 1)
    rebuilt = "+".join(f"{'' if i==0 else ''}({c})*x^{i}" for i, c in enumerate(coeffs))
    p2 = eng("poly-canon", rebuilt)
    c2 = cert_of(p2.stdout)
    record("poly-idempotent", c2 is not None and c2["claim"]["coeffs"] == coeffs,
           "same coeffs", str(c2["claim"]["coeffs"]) if c2 else p2.stderr.decode()[:80])

    # Independent oracle: coefficients of (x+1)(x-1)(x+2) = x^3+2x^2-x-2.
    record("poly-oracle", coeffs == ["-2", "-1", "2", "1"], "[-2,-1,2,1]", str(coeffs))

    # Zero polynomial.
    p = eng("poly-canon", "x-x")
    c = cert_of(p.stdout)
    record("poly-zero", c["claim"]["degree"] == "-1" and c["claim"]["coeffs"] == ["0"],
           'degree "-1" coeffs ["0"]', json.dumps(c["claim"]))

    # Decimal coefficient exactness: 0.5*x == 1/2 x, and 0.1+0.2 coefficient == 3/10.
    p = eng("poly-eq", "0.5*x+0.1+0.2", "1/2*x+3/10" if False else "x/2+3/10")
    c = cert_of(p.stdout)
    record("poly-decimal-exact", p.returncode == 0 and c["claim"]["equal"] is True,
           "equal", json.dumps(c["claim"])[:120])

    # Degree budget boundary: x^64 accepted, x^65 refused.
    p = eng("poly-canon", "x^64")
    record("poly-deg-64", p.returncode == 0 and cert_of(p.stdout)["claim"]["degree"] == "64",
           "accept deg 64", p.stdout.decode()[:60])
    p = eng("poly-canon", "x^65")
    record("poly-deg-65-refuse", p.returncode != 0, "poly-budget", p.stderr.decode()[:80])
    p = eng("poly-canon", "x^60*x^5")
    record("poly-deg-expand-refuse", p.returncode != 0, "poly-budget", p.stderr.decode()[:80])

    # ratfunc: x/x, 0/x, zero-denominator refusal, non-cancellable.
    p = eng("ratfunc-canon", "x/x")
    c = cert_of(p.stdout)
    record("ratfunc-x-over-x",
           c["claim"]["num_coeffs"] == ["1"] and c["claim"]["den_coeffs"] == ["1"]
           and c["claim"]["side_condition"] == "denominator-nonzero",
           "1/1 + side condition", json.dumps(c["claim"])[:140])
    p = eng("ratfunc-canon", "0/x")
    c = cert_of(p.stdout)
    record("ratfunc-zero-num",
           c["claim"]["num_coeffs"] == ["0"] and c["claim"]["den_coeffs"] == ["1"],
           "0/1", json.dumps(c["claim"])[:120])
    p = eng("ratfunc-canon", "x/(x-x)")
    record("ratfunc-zero-den-refuse", p.returncode != 0, "refuse",
           f"rc={p.returncode} {p.stderr.decode()[:60]}")

    # verifier agreement on all cert-bearing rows above (already called per row).

    # Sturm: repeated roots collapse to distinct; near-equal roots separate.
    p = eng("roots-isolate", "(x-1)^4*(x+2)")
    c = cert_of(p.stdout)
    record("sturm-multiplicity",
           c["claim"]["distinct_real_roots"] == "2" and verify_cert(c)[0] == 0,
           "2 distinct", json.dumps(c["claim"])[:120])
    p = eng("roots-isolate", "(x-1)*(x-1000001/1000000)")
    c = cert_of(p.stdout)
    ivs = [(Fraction(a), Fraction(b)) for a, b in c["claim"]["intervals"]]
    ok = (len(ivs) == 2 and ivs[0][1] < ivs[1][0]
          and ivs[0][0] < 1 <= ivs[0][1] and
          ivs[1][0] < Fraction(1000001, 1000000) <= ivs[1][1]
          and verify_cert(c)[0] == 0)
    record("sturm-close-roots", ok, "separated 1 vs 1.000001",
           json.dumps(c["claim"]["intervals"]))
    p = eng("roots-isolate", "5")
    c = cert_of(p.stdout)
    record("sturm-constant", p.returncode == 0 and c["claim"]["distinct_real_roots"] == "0",
           "0 roots", p.stdout.decode()[:60])
    p = eng("roots-isolate", "x-x")
    record("sturm-zero-poly-refuse", p.returncode != 0, "refuse", f"rc={p.returncode}")
    p = eng("roots-isolate", "x^2+1")
    c = cert_of(p.stdout)
    record("sturm-no-real-roots", c["claim"]["distinct_real_roots"] == "0",
           "0 roots", json.dumps(c["claim"])[:80])

    # alg-cmp: equality across different polynomials; strict order; not-isolating.
    p = eng("alg-cmp", "x^2-4", "1", "3", "x-2", "0", "3")
    record("alg-cmp-equal-cross-poly", p.returncode == 0 and b"order=equal" in p.stdout,
           "equal", p.stdout.decode()[:80])
    p = eng("alg-cmp", "x^2-2", "1", "3/2", "x^2-3", "3/2", "2")
    record("alg-cmp-sqrt2-lt-sqrt3", b"order=less" in p.stdout, "less",
           p.stdout.decode()[:80])
    p = eng("alg-cmp", "x^2-4", "-3", "3", "x-2", "0", "3")
    record("alg-cmp-not-isolating-refuse", p.returncode != 0, "refuse",
           f"rc={p.returncode} {p.stderr.decode()[:60]}")


def audit_canon() -> None:
    # Determinism: byte-identical across runs.
    a = eng("canon", "2+3*sin(pi/6)^2").stdout
    b = eng("canon", "2+3*sin(pi/6)^2").stdout
    record("canon-deterministic", a == b and a != b"", "byte-identical", a.decode()[:80])
    # Whitespace-insensitive canonicalization (same AST -> same hash).
    h = lambda out: re.search(rb"sha256=([0-9a-f]{64})", out).group(1)
    record("canon-whitespace-stable",
           h(eng("canon", "1+2*x").stdout) == h(eng("canon", " 1 + 2 * x ").stdout),
           "same hash", "ws-insensitive")
    # Injectivity probes: structurally distinct trees -> distinct hashes.
    pairs = [("1+2", "2+1"), ("ln(x*x)", "ln(x)+ln(x)"), ("x-1", "0-(1-x)"),
             ("2", "2.0"), ("min(x,2)", "min(2,x)")]
    for l, r in pairs:
        hl, hr = h(eng("canon", l).stdout), h(eng("canon", r).stdout)
        record(f"canon-distinct({l!r}vs{r!r})", hl != hr, "different hash",
               f"{hl[:8]}.. vs {hr[:8]}..")
    # Negative zero has no distinct representation: -0 folds to canonical 0.
    p = eng("rat", "0-0")
    record("negzero-rat", b"exact=0" in p.stdout, "exact=0", p.stdout.decode()[:80])
    p = eng("poly-canon", "0*x-0")
    c = cert_of(p.stdout)
    record("negzero-poly", c["claim"]["coeffs"] == ["0"], '["0"]',
           json.dumps(c["claim"])[:80])


# ---------------------------------------------------------- C/D: formal + receipts
def canon_tok(t: str) -> str:
    f = Fraction(t)
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


def producer_cert(producer: str, expr: str, lo: str, hi: str,
                  extra: list[str] | None = None) -> bytes | None:
    p = run(sys.executable, "-I", "-S", "-B", str(ROOT / "tools" / producer),
            "emit", *(extra or []), f"--expression={expr}",
            f"--lower={lo}", f"--upper={hi}")
    return p.stdout if p.returncode == 0 else None


def check_cert(cert: bytes, expr: str, lo: str, hi: str) -> tuple[int, str]:
    p = run(str(CHECKER), "/dev/stdin", "range-bound-cert", expr,
            canon_tok(lo), canon_tok(hi), inp=cert)
    return p.returncode, (p.stdout or p.stderr).decode(errors="replace").strip()


def audit_formal_fragments() -> None:
    # Mathematical containment vs mpmath-free references (math module refs are
    # NOT proof — they are drift alarms; soundness rests on the Lean checker).
    cases = [
        ("ln_rat_producer.py", "ln(x)", "1/1000000", "1000000", None, math.log),
        ("exp_rat_producer.py", "exp(x)", "-10", "10", None, math.exp),
        ("sin_rat_producer.py", "sin(x)", "-1", "1", ["--op", "sin"], math.sin),
        ("sin_rat_producer.py", "cos(x)", "-1/2", "1", ["--op", "cos"], math.cos),
        ("atan_rat_producer.py", "atan(x)", "-1000000", "1000000", None, math.atan),
    ]
    for prod, expr, lo, hi, extra, fn in cases:
        cert = producer_cert(prod, expr, lo, hi, extra)
        if cert is None:
            record(f"formal-{expr}[{lo},{hi}]", False, "producer emit", "refused")
            continue
        rc, out = check_cert(cert, expr, lo, hi)
        m = re.search(r"output (\S+) (\S+)", out)
        if rc != 0 or not m:
            record(f"formal-{expr}[{lo},{hi}]", False, "ACCEPT", out[:120])
            continue
        olo, ohi = Fraction(m.group(1)), Fraction(m.group(2))
        vals = [fn(float(Fraction(lo))), fn(float(Fraction(hi))),
                fn((float(Fraction(lo)) + float(Fraction(hi))) / 2)]
        contained = all(float(olo) - 1e-12 <= v <= float(ohi) + 1e-12 for v in vals)
        record(f"formal-{expr}[{lo},{hi}]", contained,
               "checker ACCEPT + reference containment",
               f"[{float(olo):.9g},{float(ohi):.9g}]")

    # tanh composite across the budget, containment + [-1,1] envelope.
    expr = "1-2/(exp(2*x)+1)"
    cert = producer_cert("tanh_rat_producer.py", expr, "-20", "20")
    rc, out = check_cert(cert, expr, "-20", "20")
    m = re.search(r"output (\S+) (\S+)", out)
    olo, ohi = Fraction(m.group(1)), Fraction(m.group(2))
    # Outward ε/τ pads legitimately exceed [-1,1] by ≤ ~2e-15 on the composite;
    # the sound claims are containment of ±tanh(20) and pad-scale envelope.
    ok = (rc == 0 and float(olo) <= -math.tanh(20) <= math.tanh(20) <= float(ohi)
          and abs(float(olo) + 1) < 1e-9 and abs(float(ohi) - 1) < 1e-9)
    record("formal-tanh[-20,20]", ok, "contains ±tanh(20), envelope within pads",
           f"[{float(olo):.12g},{float(ohi):.12g}]")

    # Endpoint-reversal and domain refusals at the CHECKER (not just producer).
    good = producer_cert("ln_rat_producer.py", "ln(x)", "2", "3")
    swapped = good.replace(b"input 2 3", b"input 3 2")
    rc, out = check_cert(swapped, "ln(x)", "3", "2")
    record("checker-reversed-input-refuse", rc != 0, "REJECT", out[:80])

    # Relabel a pure-Q strategy node to its TCB twin: must REJECT (release fragment).
    tcb = good.replace(b" ln_rat ", b" ln ")
    rc, out = check_cert(tcb, "ln(x)", "2", "3")
    record("checker-tcb-op-refuse", rc != 0, "REJECT", out[:80])

    # Unknown node op fails closed.
    unk = good.replace(b" ln_rat ", b" ln_magic ")
    rc, out = check_cert(unk, "ln(x)", "2", "3")
    record("checker-unknown-op-refuse", rc != 0, "REJECT", out[:80])

    # Unknown extra field on a schema'd op fails closed (codec admission).
    extra_field = good.replace(b"] n ", b"] zz 7 n ")
    rc, out = check_cert(extra_field, "ln(x)", "2", "3")
    record("checker-unknown-field-refuse", rc != 0, "REJECT", out[:80])

    # Noncanonical rational token in cert input fails closed.
    noncanon = good.replace(b"input 2 3", b"input 2/1 3")
    rc, out = check_cert(noncanon, "ln(x)", "2", "3")
    record("checker-noncanonical-rat-refuse", rc != 0, "REJECT", out[:80])

    # sin midpoint domain boundary: midpoint exactly 1 accepts, beyond refuses.
    c1 = producer_cert("sin_rat_producer.py", "sin(x)", "1", "1", ["--op", "sin"])
    record("sin-midpoint-1-accept", c1 is not None and
           check_cert(c1, "sin(x)", "1", "1")[0] == 0, "ACCEPT", "midpoint=1")
    c2 = producer_cert("sin_rat_producer.py", "sin(x)", "1", "1000001/1000000",
                       ["--op", "sin"])
    record("sin-midpoint-beyond-refuse", c2 is None, "producer refuse",
           "midpoint>1")
    # And a HAND-FORGED beyond-domain cert must be checker-refused too.
    forged = (b"jackal-eval-cert v2\nmodel jackal-iv-model-v1\nexe t\nstatus bounded\n"
              b"expr (call sin (var x))\nsource dGVzdA==\ninput 3/2 3/2\nroot 1\n"
              b"output -1 1\nnode 0 var children[] out[3/2,3/2] name x\n"
              b"node 1 sin_rat children[0] out[-1,1]\nend\n")
    rc, out = check_cert(forged, "sin(x)", "3/2", "3/2")
    record("sin-forged-beyond-domain-refuse", rc != 0, "REJECT", out[:80])


def audit_exact_verifier_adversarial() -> None:
    # -0 and +int and leading-zero tokens must be rejected by the verifier.
    base = cert_of(eng("mod-inv", "3", "7").stdout)
    for field, val, rid in [
        (("claim", "inv"), "-0", "verify-minus-zero"),
        (("claim", "inv"), "+5", "verify-plus-token"),
        (("claim", "inv"), "05", "verify-leading-zero"),
    ]:
        bad = json.loads(json.dumps(base))
        bad[field[0]][field[1]] = val
        rc, out = verify_cert(bad)
        record(rid, rc != 0, "REJECT", out[:80])
    # Unknown kind and extra top-level key.
    bad = json.loads(json.dumps(base)); bad["kind"] = "mod-magic"
    rc, out = verify_cert(bad)
    record("verify-unknown-kind", rc != 0, "REJECT", out[:80])
    bad = json.loads(json.dumps(base)); bad["extra"] = 1
    rc, out = verify_cert(bad)
    record("verify-extra-toplevel", rc != 0, "REJECT", out[:80])
    # Duplicate JSON key (raw bytes).
    raw = json.dumps(base, sort_keys=True, separators=(",", ":")).encode()
    dup = raw.replace(b'"schema":', b'"schema":"x","schema":', 1)
    p = run(sys.executable, "-I", "-S", "-B", str(VERIFIER), "-", inp=dup)
    record("verify-duplicate-key", p.returncode != 0, "REJECT",
           (p.stdout or p.stderr).decode()[:80])


def main() -> int:
    audit_number_theory()
    audit_polynomials()
    audit_canon()
    audit_formal_fragments()
    audit_exact_verifier_adversarial()
    failures = [r for r in ROWS if not r["ok"]]
    doc = {
        "schema": "jackal-seal-audit-v1",
        "release_epoch": "v1.5.0",
        "engine": hashlib.sha256(Path(ENGINE).read_bytes()).hexdigest(),
        "checker": hashlib.sha256(CHECKER.read_bytes()).hexdigest(),
        "rows": ROWS,
        "verdict": "PASS" if not failures else "FAIL",
    }
    EVIDENCE.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    print(f"evidence={EVIDENCE}")
    print(f"SEAL_AUDIT_{'PASS' if not failures else 'FAIL'} "
          f"rows={len(ROWS)} failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
