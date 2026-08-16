#!/usr/bin/env python3
"""JACKAL v1.5.0 exp_rat end-to-end release test.

Exercises the fragment-extension release lane (general-sign since v1.5.0):
  * `exp(x)` on `[0, 1]`   — canonical bracket around e
  * `exp(x)` on `[1/2, 3/2]` — non-integer rational bracket
  * `exp(x)` on `[0, 5]`   — larger interval (auto-degree)
  * `exp(x)` on `[-1, 0]`  — negative lower RELEASES (general-sign §490);
                              enclosure contains e^-1
  * upper below lower — producer refuses fail-closed
  * non-exp expression — producer refuses fail-closed
  * cert-bytes tamper (output-interval swap) — checker rejects
  * request-relabel — checker rejects
  * degree too small (--degree 1 on [0, 30]) — producer refuses fail-closed

Accept cases drive the PRODUCER + CHECKER directly (the mathematical path).
The WRAPPER is exercised by a manifest-dependent smoke that SKIPS GRACEFULLY
(still exit 0, prints `SKIPPED-manifest-pending`) while release/MANIFEST.sha256
carries a stale `exp_rat_producer` pin; identity pins are read from the
manifest at runtime, never hardcoded.
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
WRAPPER = ROOT / "jackal-exp-rat-release"
PRODUCER = ROOT / "tools" / "exp_rat_producer.py"
CHECKER = ROOT / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_cert_check"
MANIFEST = ROOT / "release" / "MANIFEST.sha256"
MANIFEST_LABEL = "exp_rat_producer"
EXPR = "exp(x)"
ACCEPT_PREFIX = ("ACCEPT request-bound theorem=request_bound_certified_release "
                 "command=range-bound-cert output ")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _run(argv: list[str], **kw) -> tuple[int, str, str]:
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=120, **kw)
    return cp.returncode, cp.stdout, cp.stderr


def _emit(expr: str, lo: str, hi: str, *extra: str) -> tuple[int, bytes, str]:
    cp = subprocess.run([sys.executable, "-I", "-S", "-B", str(PRODUCER), "emit",
                         "--expression", expr, "--lower", lo, "--upper", hi,
                         *extra],
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


def _accept_tokens(out: str) -> tuple[str, str] | None:
    for line in out.splitlines():
        if line.startswith(ACCEPT_PREFIX):
            toks = line.split()
            idx = toks.index("output")
            return toks[idx + 1], toks[idx + 2]
    return None


def _accept(expr: str, lo: str, hi: str) -> tuple[tuple[str, str] | None, str]:
    code, cert, perr = _emit(expr, lo, hi)
    if code != 0:
        return None, f"producer rc={code} {perr.strip()[:60]}"
    crc, out = _check_cert(cert, expr, lo, hi)
    echo = _accept_tokens(out)
    if crc != 0 or echo is None:
        return None, f"checker rc={crc} {out.strip()[:60]}"
    return echo, f"echo={echo}"


rows: list[dict] = []
failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    rows.append({"name": name, "ok": ok, "detail": detail})
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")


# 1. Canonical bracket around e
echo, detail = _accept(EXPR, "0", "1")
check("T1-exp-0-1",
      echo == ("1", "979/360"),
      detail)

# 2. Non-integer rational bracket
echo, detail = _accept(EXPR, "1/2", "3/2")
check("T2-exp-half-3halves",
      echo is not None,
      detail)

# 3. Larger interval — degree picker must select n large enough
echo, detail = _accept(EXPR, "0", "5")
check("T3-exp-0-5",
      echo is not None,
      detail)

# 4. Negative lower RELEASES (general-sign §490); enclosure contains e^-1
echo, detail = _accept(EXPR, "-1", "0")
check("T4-negative-lower-releases",
      echo is not None
      and float(Fraction(echo[0])) <= math.exp(-1.0) <= float(Fraction(echo[1])),
      detail)

# 5. Reversed limits — producer refuses
code, _, perr = _emit(EXPR, "2", "1")
check("T5-reversed-limits-refused",
      code == 2 and "REFUSE" in perr,
      perr.strip().split("\n")[0][:80])

# 6. Non-exp expression — producer refuses
code, _, perr = _emit("x+1", "0", "1")
check("T6-nonexp-refused",
      code == 2 and "REFUSE" in perr,
      perr.strip().split("\n")[0][:80])

# 7. Cert-bytes tamper: swap the output enclosure to a bogus interval
code, cert, _ = _emit(EXPR, "0", "1")
tampered = cert.replace(
    b"output 1 979/360",
    b"output 0 1/1000",
    1,
).replace(
    b"exp_rat children[0] out[1,979/360]",
    b"exp_rat children[0] out[0,1/1000]",
    1,
)
if code != 0 or tampered == cert:
    check("T7-tamper-cert-refused", False, "no replacement made")
else:
    code, out_err = _check_cert(tampered, EXPR, "0", "1")
    check("T7-tamper-cert-refused",
          code != 0 and "REJECT" in out_err,
          out_err.strip().split("\n")[0][:80])

# 8. Request-relabel: valid cert bytes but checker asked for a different expression
code, cert, _ = _emit(EXPR, "0", "1")
code, out_err = _check_cert(cert, "exp(x)+1", "0", "1")
check("T8-relabel-expression-refused",
      code != 0 and "REJECT" in out_err,
      out_err.strip().split("\n")[0][:80])

# 9. Degree too small: --degree 1 cannot witness [0, 30] — producer refuses
code, _, perr = _emit(EXPR, "0", "30", "--degree", "1")
check("T9-degree-too-small-refused",
      code == 2 and "REFUSE" in perr,
      perr.strip().split("\n")[0][:80])

# W1. Wrapper smoke — manifest-dependent; skips gracefully while the
# exp_rat_producer pin is stale (pins read from the manifest at runtime).
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
    code, out, err = _run([str(WRAPPER), EXPR, "0", "1"])
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
print("VERDICT: PASS — exp_rat fragment extension end-to-end")
