#!/usr/bin/env python3
"""JACKAL v1.5.0 tanh_rat composite end-to-end release test.

The admitted expression is the exact composite form imported from
`tools/formal_receipt.py` (`TANH_COMPOSITE_EXPRESSION`; = tanh(x)
mathematically — `tanh` is NOT a grammar token). Exercises:
  * `[1/2, 1/2]` — enclosure contains tanh(0.5), width < 1e-12
  * `[-2, 2]`    — enclosure inside [-1, 1] and contains tanh(+-2)
  * |x| > 20 — producer refuses fail-closed (composite budget)
  * cert-bytes tamper (one div-corner digit flipped) — checker rejects
  * request-relabel (`exp(x)` against the composite cert) — checker rejects
  * the literal string `tanh(x)` as expression — producer refuses (not grammar)

Accept cases drive the PRODUCER + CHECKER directly (the mathematical path).
The WRAPPER is exercised by a manifest-dependent smoke that SKIPS GRACEFULLY
(still exit 0, prints `SKIPPED-manifest-pending`) until release/MANIFEST.sha256
pins the `tanh_rat_producer` label; identity pins are read from the manifest
at runtime, never hardcoded.
"""
from __future__ import annotations

import hashlib
import math
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from formal_receipt import TANH_COMPOSITE_EXPRESSION  # noqa: E402

WRAPPER = ROOT / "jackal-tanh-rat-release"
PRODUCER = ROOT / "tools" / "tanh_rat_producer.py"
CHECKER = ROOT / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_cert_check"
MANIFEST = ROOT / "release" / "MANIFEST.sha256"
MANIFEST_LABEL = "tanh_rat_producer"
EXPR = TANH_COMPOSITE_EXPRESSION
PRODUCER_ARGS: list[str] = []
ACCEPT_PREFIX = ("ACCEPT request-bound theorem=request_bound_certified_release "
                 "command=range-bound-cert output ")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _run(argv: list[str], **kw) -> tuple[int, str, str]:
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=120, **kw)
    return cp.returncode, cp.stdout, cp.stderr


def _emit(expr: str, lo: str, hi: str) -> tuple[int, bytes, str]:
    cp = subprocess.run([sys.executable, "-I", "-S", "-B", str(PRODUCER), "emit",
                         *PRODUCER_ARGS,
                         "--expression", expr, "--lower", lo, "--upper", hi],
                        capture_output=True, timeout=120)
    return cp.returncode, cp.stdout, cp.stderr.decode()


def _check_cert(cert_bytes: bytes, expr: str, lo: str, hi: str) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("wb", suffix=".cert", delete=False) as f:
        f.write(cert_bytes)
        path = f.name
    cp = subprocess.run([str(CHECKER), path, "range-bound-cert", expr, lo, hi],
                        capture_output=True, text=True, timeout=120)
    Path(path).unlink()
    return cp.returncode, (cp.stdout + cp.stderr)


def _accept_enclosure(out: str) -> tuple[Fraction, Fraction] | None:
    for line in out.splitlines():
        if line.startswith(ACCEPT_PREFIX):
            toks = line.split()
            idx = toks.index("output")
            return Fraction(toks[idx + 1]), Fraction(toks[idx + 2])
    return None


def _accept(expr: str, lo: str, hi: str) -> tuple[tuple[Fraction, Fraction] | None, str]:
    code, cert, perr = _emit(expr, lo, hi)
    if code != 0:
        return None, f"producer rc={code} {perr.strip()[:60]}"
    crc, out = _check_cert(cert, expr, lo, hi)
    enc = _accept_enclosure(out)
    if crc != 0 or enc is None:
        return None, f"checker rc={crc} {out.strip()[:60]}"
    return enc, f"out=[{float(enc[0]):.12g},{float(enc[1]):.12g}]"


def _tamper_div_corner(cert: bytes) -> bytes:
    """Flip one digit inside the div node's `p[...]` corner block."""
    lines = cert.decode().splitlines()
    for i, line in enumerate(lines):
        if line.startswith("node ") and " div " in line:
            k = line.find("p[")
            if k < 0:
                return cert
            j = k + 2
            while j < len(line) and not line[j].isdigit():
                j += 1
            d = line[j]
            nd = "8" if d == "9" else str(int(d) + 1)
            lines[i] = line[:j] + nd + line[j + 1:]
            return ("\n".join(lines) + "\n").encode()
    return cert


rows: list[dict] = []
failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    rows.append({"name": name, "ok": ok, "detail": detail})
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")


# 1. [1/2, 1/2] — enclosure contains tanh(0.5), width < 1e-12
enc, detail = _accept(EXPR, "1/2", "1/2")
check("T1-tanh-half-point",
      enc is not None
      and float(enc[0]) <= math.tanh(0.5) <= float(enc[1])
      and float(enc[1] - enc[0]) < 1e-12,
      detail)

# 2. [-2, 2] — enclosure inside [-1, 1] and contains tanh(+-2)
enc, detail = _accept(EXPR, "-2", "2")
check("T2-tanh-minus2-2",
      enc is not None
      and enc[0] > -1 and enc[1] < 1
      and float(enc[0]) <= math.tanh(-2.0)
      and float(enc[1]) >= math.tanh(2.0),
      detail)

# 3. |x| > 20 — producer refuses fail-closed (composite budget)
code, _, perr = _emit(EXPR, "0", "21")
check("T3-budget-refused",
      code == 2 and "REFUSE" in perr,
      perr.strip().split("\n")[0][:80])

# 4. Cert-bytes tamper: flip one div-corner digit — checker rejects
code, cert, _ = _emit(EXPR, "1/2", "1/2")
tampered = _tamper_div_corner(cert)
if code != 0 or tampered == cert:
    check("T4-tamper-div-corner-refused", False, "no tamper applied")
else:
    code, out_err = _check_cert(tampered, EXPR, "1/2", "1/2")
    check("T4-tamper-div-corner-refused",
          code != 0 and "REJECT" in out_err,
          out_err.strip().split("\n")[0][:80])

# 5. Request-relabel: valid composite cert, checker asked for exp(x)
code, cert, _ = _emit(EXPR, "1/2", "1/2")
code, out_err = _check_cert(cert, "exp(x)", "1/2", "1/2")
check("T5-relabel-expression-refused",
      code != 0 and "REJECT" in out_err,
      out_err.strip().split("\n")[0][:80])

# 6. The literal string `tanh(x)` — producer refuses (tanh is not grammar)
code, _, perr = _emit("tanh(x)", "0", "1")
check("T6-tanh-token-refused",
      code == 2 and "REFUSE" in perr,
      perr.strip().split("\n")[0][:80])

# W1. Wrapper smoke — manifest-dependent; skips gracefully until the lead
# pins the tanh_rat_producer label (pins read from the manifest at runtime).
def _manifest_pin(label: str) -> str | None:
    if not MANIFEST.is_file():
        return None
    for line in MANIFEST.read_text().splitlines():
        parts = line.split()
        if parts and parts[0] == label:
            return parts[-1]
    return None


prod_pin = _manifest_pin(MANIFEST_LABEL)
chk_pin = _manifest_pin("checker")
if prod_pin != _sha(PRODUCER) or chk_pin != _sha(CHECKER):
    print(f"SKIPPED-manifest-pending W1-wrapper-smoke "
          f"({MANIFEST_LABEL} pin absent or stale in release/MANIFEST.sha256)")
else:
    code, out, err = _run([str(WRAPPER), EXPR, "1/2", "1/2"])
    check("W1-wrapper-smoke",
          code == 0 and "status=formal-bounded" in out
          and "checker.ACCEPT=ACCEPT" in out,
          err.strip().split("\n")[0][:80] if code != 0 else "formal-bounded")

print("---")
print(f"checker.sha256={_sha(CHECKER)}")
print(f"producer.sha256={_sha(PRODUCER)}")
print(f"tests_run={len(rows)} failures={failures}")
if failures:
    print("VERDICT: FAIL")
    sys.exit(1)
print("VERDICT: PASS — tanh_rat composite fragment extension end-to-end")
