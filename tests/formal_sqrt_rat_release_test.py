#!/usr/bin/env python3
"""JACKAL v1.4.0 sqrt_rat end-to-end release test.

Exercises the fragment-extension path:

  1. `sqrt(x)` on `[4, 9]` → perfect-square bracket, exact `[2, ~3]` ACCEPT.
  2. `sqrt(x)` on `[2, 3]` → irrational bracket, high-precision rational ACCEPT.
  3. `sqrt(x)` on `[0, 1]`  → boundary case lo = 0.
  4. `sqrt(x)` on `[1/4, 1/9]` reversed (upper < lower) → REFUSED.
  5. `x+1` sent to the sqrt_rat producer → REFUSED at producer.
  6. Tampered cert: swap the enclosure bytes → checker REJECT.

Every ACCEPT line is required to carry `output <lo> <hi>` in the
request-bound checker echo — the ACCEPT is meaningless without it.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "jackal-sqrt-rat-release"
PRODUCER = ROOT / "tools" / "sqrt_rat_producer.py"
CHECKER = ROOT / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_cert_check"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _run(argv: list[str], **kw) -> tuple[int, str, str]:
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=60, **kw)
    return cp.returncode, cp.stdout, cp.stderr


def _accept_echo(stdout: str) -> tuple[str, str] | None:
    for line in stdout.splitlines():
        if line.startswith("checker.ACCEPT="):
            payload = line[len("checker.ACCEPT="):]
            marker = "command=range-bound-cert output "
            if marker not in payload:
                return None
            tail = payload.split(marker, 1)[1].strip()
            parts = tail.split(" ")
            if len(parts) != 2:
                return None
            return parts[0], parts[1]
    return None


def _release(expr: str, lo: str, hi: str) -> tuple[int, str, str]:
    return _run([str(WRAPPER), expr, lo, hi])


def _emit(expr: str, lo: str, hi: str) -> bytes:
    cp = subprocess.run([sys.executable, str(PRODUCER), "emit",
                          "--expression", expr, "--lower", lo, "--upper", hi],
                         capture_output=True, timeout=60)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.decode("utf-8", "replace"))
    return cp.stdout


def _check_cert(cert_bytes: bytes, expr: str, lo: str, hi: str) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("wb", suffix=".cert", delete=False) as f:
        f.write(cert_bytes)
        p = f.name
    try:
        cp = subprocess.run([str(CHECKER), p, "range-bound-cert", expr, lo, hi],
                             capture_output=True, text=True, timeout=60)
    finally:
        Path(p).unlink()
    return cp.returncode, (cp.stdout + cp.stderr)


rows: list[dict] = []
failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    if not ok:
        failures += 1
    rows.append({"id": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")


# 1. Perfect-square bracket
code, out, err = _release("sqrt(x)", "4", "9")
echo = _accept_echo(out)
check("T1-perfect-square-4-9",
      code == 0 and "status=formal-bounded" in out
      and echo is not None and echo[0] == "2",
      f"echo={echo}")

# 2. Irrational bracket [2, 3]
code, out, err = _release("sqrt(x)", "2", "3")
echo = _accept_echo(out)
check("T2-irrational-2-3",
      code == 0 and echo is not None
      and echo[0].count("/") == 1 and echo[1].count("/") == 1,
      f"echo={echo[0][:24]}../..{echo[1][-24:] if echo else '?'}")

# 3. Boundary lo=0
code, out, err = _release("sqrt(x)", "0", "1")
echo = _accept_echo(out)
check("T3-boundary-lo-zero",
      code == 0 and echo is not None and echo[0] == "0",
      f"echo={echo}")

# 4. Reversed limits — producer refuses
code, out, err = _release("sqrt(x)", "9", "4")
check("T4-reversed-limits-refused",
      code != 0 and "reason=producer-refused" in err,
      err.strip().split("\n")[0][:80])

# 5. Non-sqrt expression — producer refuses
code, out, err = _release("x+1", "1", "2")
check("T5-nonsqrt-refused",
      code != 0 and "reason=producer-refused" in err,
      err.strip().split("\n")[0][:80])

# 6. Cert-bytes tamper: swap output enclosure to a bogus interval
cert = _emit("sqrt(x)", "4", "9")
tampered = cert.replace(
    b"node 1 sqrt_rat children[0] out[2,30000000000000000000000000000000000000001/10000000000000000000000000000000000000000]",
    b"node 1 sqrt_rat children[0] out[100,200]"
)
if tampered == cert:
    check("T6-tamper-cert-refused", False, "no replacement made")
else:
    code, out_err = _check_cert(tampered, "sqrt(x)", "4", "9")
    check("T6-tamper-cert-refused",
          code != 0 and "REJECT" in out_err,
          out_err.strip().split("\n")[0][:80])

# 7. Wrong expected expression through the checker CLI
cert = _emit("sqrt(x)", "4", "9")
code, out_err = _check_cert(cert, "sqrt(x)+1", "4", "9")
check("T7-relabel-expression-refused",
      code != 0 and "REJECT" in out_err,
      out_err.strip().split("\n")[0][:80])

print("---")
print(f"checker.sha256={_sha(CHECKER)}")
print(f"producer.sha256={_sha(PRODUCER)}")
print(f"tests_run={len(rows)} failures={failures}")
if failures:
    print("VERDICT: FAIL")
    sys.exit(1)
print("VERDICT: PASS — sqrt_rat fragment extension end-to-end")
