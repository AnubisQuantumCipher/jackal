#!/usr/bin/env python3
"""JACKAL v1.7.2 integrate-bound-cert end-to-end release test.

Exercises the certified composed-integral release lane:

  * `sin(x)` on `[0, 1]` tol 1/100      — smooth taylor4 single leaf
  * `abs(x-1/3)` on `[0, 1]` tol 1/40   — multi-level range-only tree
  * `x^3-x` on `[-1, 3/2]` tol 1/8      — signed left/right child sums
  * oracle containment                  — mpmath 50-dps value inside each
                                          released enclosure
  * reversed domain                     — wrapper/binder refuses fail-closed
  * non-fragment expression (`tan(x)`)  — producer refuses fail-closed
  * cert-bytes tamper (narrowed output) — checker rejects (forged-enclosure
                                          or released-interval-mismatch)
  * stale checker pin relabel           — checker rejects (stale-identity)
  * WRAPPER end-to-end                  — ./jackal-int-cert-release emits a
                                          receipt, re-verified via
                                          tools/receipt_verify.py CLI with
                                          manifest pins; then a receipt
                                          enclosure tamper must refuse.

Identity pins are read from release/MANIFEST.sha256 at runtime, never
hardcoded.  Runnable under `python3 -O`.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "jackal-int-cert-release"
PRODUCER = ROOT / "tools" / "int_cert_producer.py"
CHECKER = ROOT / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_int_cert_check"
MANIFEST = ROOT / "release" / "MANIFEST.sha256"
ACCEPT_PREFIX = ("ACCEPT status=bounded theorem=int_cert_sound "
                 "checker=jackal-iv-bound-step-v1 output ")

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail[:140]}")
    if not ok:
        FAILURES.append(name)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in MANIFEST.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        rows[parts[0]] = parts[-1]
    return rows


def _emit(expr: str, lo: str, hi: str, tol: str) -> tuple[int, bytes, str]:
    cp = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(PRODUCER), "emit",
         "--expression", expr, "--lower", lo, "--upper", hi,
         "--tolerance", tol],
        capture_output=True, timeout=300)
    return cp.returncode, cp.stdout, cp.stderr.decode()


def _check_cert(cert_bytes: bytes, expr: str, lo: str, hi: str,
                tol: str) -> tuple[int, str, str]:
    with tempfile.NamedTemporaryFile(suffix=".jic", delete=False) as fh:
        fh.write(cert_bytes)
        path = fh.name
    try:
        cp = subprocess.run(
            [str(CHECKER), path, expr, lo, hi, tol],
            capture_output=True,
            text=True,
            timeout=300,
        )
        return cp.returncode, cp.stdout, cp.stderr
    finally:
        Path(path).unlink()


def _enclosure_of(cert_bytes: bytes) -> tuple[Fraction, Fraction]:
    for line in cert_bytes.decode().splitlines():
        if line.startswith("output "):
            lo, hi = line.split(" ", 1)[1].split(" ")
            return Fraction(lo), Fraction(hi)
    raise AssertionError("no output line")


def _oracle(expr: str, lo: str, hi: str):
    try:
        import mpmath
    except ImportError:
        # Dependency-free deterministic fallback for this fixed corpus.  The
        # formal checker remains authority; these are only containment
        # cross-checks and must never silently skip in a release gate.
        import math

        a, b = Fraction(lo), Fraction(hi)
        if expr == "sin(x)":
            return 1.0 - math.cos(float(b)) - (1.0 - math.cos(float(a)))
        if expr == "abs(x-1/3)":
            c = Fraction(1, 3)
            return float(((c - a) ** 2 + (b - c) ** 2) / 2)
        if expr == "x^3-x":
            antiderivative = lambda t: t ** 4 / 4 - t ** 2 / 2
            return float(antiderivative(b) - antiderivative(a))
        raise ValueError(f"oracle expression unsupported: {expr}")
    mpmath.mp.dps = 50
    fns = {
        "sin(x)": lambda t: mpmath.sin(t),
        "abs(x-1/3)": lambda t: abs(t - mpmath.mpf(1) / 3),
        "x^3-x": lambda t: t ** 3 - t,
    }
    f = fns[expr]
    return mpmath.quad(
        f,
        [
            mpmath.mpf(Fraction(lo).numerator) / Fraction(lo).denominator,
            mpmath.mpf(Fraction(hi).numerator) / Fraction(hi).denominator,
        ],
    )


def main() -> int:
    for path, name in ((PRODUCER, "producer"), (CHECKER, "checker"),
                       (WRAPPER, "wrapper"), (MANIFEST, "manifest")):
        if not path.exists():
            print(f"RED: {name} missing at {path}", file=sys.stderr)
            return 2

    rows = _manifest_rows()
    pinned_producer = rows.get("int-cert-producer", "")
    pinned_checker = rows.get("int-cert-checker", "")
    check("manifest-producer-pin", _sha(PRODUCER) == pinned_producer,
          f"live={_sha(PRODUCER)[:16]} pinned={pinned_producer[:16]}")
    check("manifest-checker-pin", _sha(CHECKER) == pinned_checker,
          f"live={_sha(CHECKER)[:16]} pinned={pinned_checker[:16]}")

    # -- accept cases: producer -> checker -> oracle containment ------------
    accepts = [
        ("sin(x)", "0", "1", "1/100"),
        ("abs(x-1/3)", "0", "1", "1/40"),
        ("x^3-x", "-1", "3/2", "1/8"),
    ]
    kept: dict[str, bytes] = {}
    for expr, lo, hi, tol in accepts:
        rc, cert, err = _emit(expr, lo, hi, tol)
        check(f"emit[{expr}]", rc == 0, err.strip())
        if rc != 0:
            continue
        kept[expr] = cert
        crc, cout, cerr = _check_cert(cert, expr, lo, hi, tol)
        check(f"checker-accept[{expr}]",
              crc == 0 and cout.startswith(ACCEPT_PREFIX), (cerr or cout).strip())
        enc_lo, enc_hi = _enclosure_of(cert)
        check(f"width[{expr}]", enc_hi - enc_lo <= Fraction(tol),
              f"width={float(enc_hi - enc_lo)}")
        try:
            truth = _oracle(expr, lo, hi)
            inside = (float(enc_lo) <= truth <= float(enc_hi))
            check(f"oracle-containment[{expr}]", bool(inside),
                  f"oracle={truth} enclosure=[{float(enc_lo)},{float(enc_hi)}]")
        except (ArithmeticError, ValueError) as exc:
            check(f"oracle-containment[{expr}]", False, str(exc))

    # -- fail-closed refusals ------------------------------------------------
    rc, _, err = _emit("tan(x)", "0", "1", "1/10")
    check("refuse-nonfragment", rc != 0 and "unsupported-expression" in err, err.strip())
    rc, _, err = _emit("x", "1", "0", "1/10")
    check("refuse-reversed", rc != 0 and "invalid-domain" in err, err.strip())

    # -- checker-side tampers -------------------------------------------------
    base = kept.get("sin(x)")
    if base is not None:
        lines = base.decode().splitlines()
        out_i = next(i for i, l in enumerate(lines) if l.startswith("output "))
        lo_s, hi_s = lines[out_i].split(" ", 1)[1].split(" ")
        third = (Fraction(hi_s) - Fraction(lo_s)) / 3
        n_lo, n_hi = Fraction(lo_s) + third, Fraction(hi_s) - third

        def frac_str(fr: Fraction) -> str:
            return str(fr.numerator) if fr.denominator == 1 else \
                f"{fr.numerator}/{fr.denominator}"

        lines[out_i] = f"output {frac_str(n_lo)} {frac_str(n_hi)}"
        tampered = ("\n".join(lines) + "\n").encode()
        trc, tout, terr = _check_cert(tampered, "sin(x)", "0", "1", "1/100")
        refused_cls = any(cls in (terr + tout) for cls in
                          ("forged-enclosure", "released-interval-mismatch"))
        check("tamper-narrowed-output", trc != 0 and refused_cls,
              (terr or tout).strip())

        stale = base.decode().replace(
            "checker jackal-iv-bound-step-v1",
            "checker jackal-iv-bound-step-v0", 1).encode()
        src, sout, serr = _check_cert(stale, "sin(x)", "0", "1", "1/100")
        check("tamper-stale-pin", src != 0 and "stale-identity" in (serr + sout),
              (serr or sout).strip())

    # -- wrapper end-to-end ---------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="jackal-int-cert-release-test-") as td:
        receipt_path = Path(td) / "receipt.json"
        wrc = subprocess.run([str(WRAPPER), "sin(x)", "0", "1", "1/100",
                              str(receipt_path)],
                             capture_output=True, text=True, timeout=600)
        wrapper_ok = (wrc.returncode == 0
                      and "status=formal-bounded" in wrc.stdout
                      and "theorem=int_cert_sound" in wrc.stdout
                      and "receipt_reverified=true" in wrc.stdout)
        check("wrapper-release", wrapper_ok, (wrc.stderr or wrc.stdout).strip())
        if wrapper_ok:
            receipt = json.loads(receipt_path.read_text())
            check("receipt-variant", receipt.get("variant") == "int_cert",
                  str(receipt.get("variant")))
            check("receipt-theorem",
                  receipt.get("theorem", {}).get("id") == "int_cert_sound",
                  str(receipt.get("theorem")))
            verify_argv = [
                sys.executable, "-I", "-S", "-B",
                str(ROOT / "tools" / "isolated_entry.py"), "verify",
                "--receipt", str(receipt_path),
                "--checker", str(CHECKER),
                "--expected-evaluator", pinned_producer,
                "--expected-checker", pinned_checker,
                "--expected-release-epoch", "v1.7.2",
                "--expected-command", "integrate-bound-cert",
                "--expected-expression", "sin(x)",
                "--expected-input-lo", "0",
                "--expected-input-hi", "1",
                "--expected-tolerance", "1/100",
                "--inventory",
                str(ROOT / "release/coverage/formal_coverage_inventory.json"),
                "--expected-inventory", rows.get("coverage-inventory", ""),
                "--proof-identity",
                str(ROOT / "release/evidence/int_cert_proof_identity_v172.json"),
                "--expected-proof-identity-file",
                rows.get("int-cert-proof-identity", ""),
                "--expected-proof-identity-digest",
                rows.get("int-cert-proof-digest", ""),
            ]
            vrc = subprocess.run(verify_argv, capture_output=True, text=True,
                                 timeout=600)
            check("receipt-reverify",
                  vrc.returncode == 0 and "status=verified verdict=ACCEPT" in vrc.stdout,
                  (vrc.stderr or vrc.stdout).strip())

            poisoned = json.loads(receipt_path.read_text())
            poisoned["result"]["enclosure_hi"] = "99999"
            poison_path = Path(td) / "poisoned.json"
            poison_path.write_text(json.dumps(poisoned, sort_keys=True))
            prc = subprocess.run(
                [a if a != str(receipt_path) else str(poison_path)
                 for a in verify_argv],
                capture_output=True, text=True, timeout=600)
            check("receipt-tamper-refuses",
                  prc.returncode != 0 and "status=refused" in prc.stderr,
                  (prc.stderr or prc.stdout).strip())

    total = len(FAILURES)
    print(f"TOTAL failures={total}")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
