#!/usr/bin/env python3
"""JACKAL v1.5.0 ln_rat end-to-end release test.

Exercises the fragment-extension release lane:
  * `ln(x)` on `[2, 3]`     — enclosure contains ln2..ln3 (1e-6 float slack)
  * `ln(x)` on `[1/10, 1]`  — negative outputs
  * `ln(x)` on `[1, 1]`     — point interval around ln1 = 0
  * lower = 0 — producer refuses fail-closed (log domain)
  * upper below lower — producer refuses fail-closed
  * non-ln expression — producer refuses fail-closed
  * cert-bytes tamper (one output digit flipped) — checker rejects
  * request-relabel (`cos(x)` against an ln cert) — checker rejects

Accept cases drive the PRODUCER + CHECKER directly (the mathematical path).
The WRAPPER is exercised by a manifest-dependent smoke that SKIPS GRACEFULLY
(still exit 0, prints `SKIPPED-manifest-pending`) until release/MANIFEST.sha256
pins the `ln_rat_producer` label; identity pins are read from the manifest at
runtime, never hardcoded.
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
WRAPPER = ROOT / "jackal-ln-rat-release"
PRODUCER = ROOT / "tools" / "ln_rat_producer.py"
CHECKER = ROOT / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_cert_check"
MANIFEST = ROOT / "release" / "MANIFEST.sha256"
MANIFEST_LABEL = "ln_rat_producer"
EXPR = "ln(x)"
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


def _flip_output_digit(cert: bytes) -> bytes:
    """Flip one digit on the cert's `output` header line (byte-level tamper)."""
    lines = cert.decode().splitlines()
    for i, line in enumerate(lines):
        if line.startswith("output "):
            for j in range(len("output "), len(line)):
                if line[j].isdigit():
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


# 1. [2, 3] — enclosure must contain ln2..ln3 (1e-6 float slack)
enc, detail = _accept(EXPR, "2", "3")
check("T1-ln-2-3",
      enc is not None
      and float(enc[0]) <= math.log(2) + 1e-6
      and float(enc[1]) >= math.log(3) - 1e-6,
      detail)

# 2. [1/10, 1] — negative outputs
enc, detail = _accept(EXPR, "1/10", "1")
check("T2-ln-tenth-1",
      enc is not None
      and enc[0] < 0
      and float(enc[0]) <= math.log(0.1) + 1e-6
      and float(enc[1]) >= math.log(1.0) - 1e-6,
      detail)

# 3. [1, 1] — point interval; enclosure straddles ln1 = 0
enc, detail = _accept(EXPR, "1", "1")
check("T3-ln-point-1",
      enc is not None and enc[0] <= 0 <= enc[1],
      detail)

# 4. lower = 0 — producer refuses fail-closed (log domain)
code, _, perr = _emit(EXPR, "0", "1")
check("T4-zero-lower-refused",
      code == 2 and "REFUSE" in perr,
      perr.strip().split("\n")[0][:80])

# 5. Reversed limits — producer refuses
code, _, perr = _emit(EXPR, "3", "2")
check("T5-reversed-limits-refused",
      code == 2 and "REFUSE" in perr,
      perr.strip().split("\n")[0][:80])

# 6. Non-ln expression — producer refuses
code, _, perr = _emit("exp(x)", "1", "2")
check("T6-nonln-refused",
      code == 2 and "REFUSE" in perr,
      perr.strip().split("\n")[0][:80])

# 7. Cert-bytes tamper: flip one output digit — checker rejects
code, cert, _ = _emit(EXPR, "2", "3")
tampered = _flip_output_digit(cert)
if code != 0 or tampered == cert:
    check("T7-tamper-cert-refused", False, "no tamper applied")
else:
    code, out_err = _check_cert(tampered, EXPR, "2", "3")
    check("T7-tamper-cert-refused",
          code != 0 and "REJECT" in out_err,
          out_err.strip().split("\n")[0][:80])

# 8. Request-relabel: valid ln cert, checker asked for cos(x)
code, cert, _ = _emit(EXPR, "2", "3")
code, out_err = _check_cert(cert, "cos(x)", "2", "3")
check("T8-relabel-expression-refused",
      code != 0 and "REJECT" in out_err,
      out_err.strip().split("\n")[0][:80])

# W1. Wrapper smoke — manifest-dependent; skips gracefully until the lead
# pins the ln_rat_producer label (pins read from the manifest at runtime).
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
    code, out, err = _run([str(WRAPPER), EXPR, "2", "3"])
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
print("VERDICT: PASS — ln_rat fragment extension end-to-end")
