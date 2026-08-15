#!/usr/bin/env python3
"""JACKAL v1.4.1 exp_rat end-to-end release test.

Exercises the fragment-extension release lane:
  * `exp(x)` on `[0, 1]`  — canonical bracket around e
  * `exp(x)` on `[1/2, 3/2]` — non-integer rational bracket
  * `exp(x)` on `[0, 5]`  — larger interval (auto-degree)
  * negative lower — producer refuses fail-closed
  * upper below lower — producer refuses fail-closed
  * non-exp expression — producer refuses fail-closed
  * cert-bytes tamper (output-interval swap) — checker rejects
  * request-relabel — checker rejects
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "jackal-exp-rat-release"
PRODUCER = ROOT / "tools" / "exp_rat_producer.py"
CHECKER = ROOT / "proofs" / "lean" / ".lake" / "build" / "bin" / "jackal_cert_check"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _run(argv: list[str], **kw) -> tuple[int, str, str]:
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=60, **kw)
    return cp.returncode, cp.stdout, cp.stderr


def _accept_echo(stdout: str) -> tuple[str, str] | None:
    for line in stdout.splitlines():
        if line.startswith("checker.ACCEPT=ACCEPT"):
            toks = line.split()
            try:
                idx = toks.index("output")
                return toks[idx + 1], toks[idx + 2]
            except (ValueError, IndexError):
                return None
    return None


def _release(expr: str, lo: str, hi: str) -> tuple[int, str, str]:
    return _run([str(WRAPPER), expr, lo, hi])


def _emit(expr: str, lo: str, hi: str) -> bytes:
    cp = subprocess.run([sys.executable, str(PRODUCER), "emit",
                         "--expression", expr, "--lower", lo, "--upper", hi],
                        capture_output=True, check=True, timeout=60)
    return cp.stdout


def _check_cert(cert_bytes: bytes, expr: str, lo: str, hi: str) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("wb", suffix=".cert", delete=False) as f:
        f.write(cert_bytes)
        path = f.name
    cp = subprocess.run([str(CHECKER), path, "range-bound-cert", expr, lo, hi],
                        capture_output=True, text=True, timeout=60)
    Path(path).unlink()
    return cp.returncode, (cp.stdout + cp.stderr)


rows: list[dict] = []
failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    rows.append({"name": name, "ok": ok, "detail": detail})
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")


# 1. Canonical bracket around e
code, out, err = _release("exp(x)", "0", "1")
echo = _accept_echo(out)
check("T1-exp-0-1",
      code == 0 and echo == ("1", "979/360"),
      f"echo={echo}")

# 2. Non-integer rational bracket
code, out, err = _release("exp(x)", "1/2", "3/2")
echo = _accept_echo(out)
check("T2-exp-half-3halves",
      code == 0 and echo is not None,
      f"echo={echo}")

# 3. Larger interval — degree picker must select n large enough
code, out, err = _release("exp(x)", "0", "5")
echo = _accept_echo(out)
check("T3-exp-0-5",
      code == 0 and echo is not None,
      f"echo={echo}")

# 4. Negative lower — producer refuses fail-closed (positive branch only)
code, out, err = _release("exp(x)", "-1", "1")
check("T4-negative-lower-refused",
      code != 0 and "reason=producer-refused" in err,
      err.strip().split("\n")[0][:80])

# 5. Reversed limits — producer refuses
code, out, err = _release("exp(x)", "2", "1")
check("T5-reversed-limits-refused",
      code != 0 and "reason=producer-refused" in err,
      err.strip().split("\n")[0][:80])

# 6. Non-exp expression — producer refuses
code, out, err = _release("x+1", "0", "1")
check("T6-nonexp-refused",
      code != 0 and "reason=producer-refused" in err,
      err.strip().split("\n")[0][:80])

# 7. Cert-bytes tamper: swap the output enclosure to a bogus interval
cert = _emit("exp(x)", "0", "1")
tampered = cert.replace(
    b"output 1 979/360",
    b"output 0 1/1000",
    1,
).replace(
    b"exp_rat children[0] out[1,979/360]",
    b"exp_rat children[0] out[0,1/1000]",
    1,
)
if tampered == cert:
    check("T7-tamper-cert-refused", False, "no replacement made")
else:
    code, out_err = _check_cert(tampered, "exp(x)", "0", "1")
    check("T7-tamper-cert-refused",
          code != 0 and "REJECT" in out_err,
          out_err.strip().split("\n")[0][:80])

# 8. Request-relabel: valid cert bytes but checker asked for a different expression
cert = _emit("exp(x)", "0", "1")
code, out_err = _check_cert(cert, "exp(x)+1", "0", "1")
check("T8-relabel-expression-refused",
      code != 0 and "REJECT" in out_err,
      out_err.strip().split("\n")[0][:80])

print("---")
print(f"checker.sha256={_sha(CHECKER)}")
print(f"producer.sha256={_sha(PRODUCER)}")
print(f"tests_run={len(rows)} failures={failures}")
if failures:
    print("VERDICT: FAIL")
    sys.exit(1)
print("VERDICT: PASS — exp_rat fragment extension end-to-end")
