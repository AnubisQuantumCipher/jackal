#!/usr/bin/env python3
"""Compare unchanged checkers on public synthetic fixtures; no private receipts.

These are compatibility controls for a development guest, not a release gate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from development_runner import call_guest

ROOT = Path(__file__).resolve().parents[2]


def check(guest: Path, runtime: Path) -> list[dict]:
    range_certificate = subprocess.check_output([
        sys.executable, "-I", "-S", "-B", str(ROOT / "tools/sqrt_rat_producer.py"),
        "emit", "--expression", "sqrt(x)", "--lower", "1", "--upper", "4"], timeout=300)
    integral_certificate = subprocess.check_output([
        sys.executable, "-I", "-S", "-B", str(ROOT / "tools/int_cert_producer.py"),
        "emit", "--expression", "0", "--lower", "0", "--upper", "1",
        "--tolerance", "2"], timeout=300)
    manifest = json.loads((guest / "development-manifest.json").read_bytes())
    rows = []
    contexts = [
        (0, "range", "jackal_cert_check", range_certificate,
         ["range-bound-cert", "sqrt(x)", "1", "4"], 1),
        (1, "archival-range", "jackal_cert_check_v170", range_certificate,
         ["range-bound-cert", "sqrt(x)", "1", "4"], 1),
        (2, "integral", "jackal_int_cert_check", integral_certificate,
         ["0", "0", "1", "2"], 0),
    ]
    with tempfile.TemporaryDirectory(prefix="jackal-public-fixture-") as temporary:
        certificate_path = Path(temporary) / "certificate"
        for selected, context, checker_name, certificate, arguments, expression_index in contexts:
            checker = runtime / checker_name
            before = hashlib.sha256(checker.read_bytes()).hexdigest()
            if before != manifest["inputs"]["checkers/" + context]["sha256"]:
                raise RuntimeError("fixture checker identity mismatch: " + context)
            certificate_path.write_bytes(certificate)
            for valid in (True, False):
                actual_arguments = list(arguments)
                if not valid:
                    actual_arguments[expression_index] = "x"
                direct = subprocess.run([str(checker), str(certificate_path), *actual_arguments],
                                        capture_output=True, timeout=3600)
                if valid:
                    if direct.returncode != 0 or not direct.stdout.startswith(b"ACCEPT"):
                        raise RuntimeError("positive direct control did not accept: " + context)
                elif direct.returncode == 0:
                    raise RuntimeError("negative direct control did not refuse: " + context)
                started = time.monotonic()
                private = call_guest(guest, selected, certificate, actual_arguments)
                if (private.returncode, private.stdout, private.stderr) != (
                        direct.returncode, direct.stdout, direct.stderr):
                    raise RuntimeError(json.dumps({"context": context, "comparison": "mismatch",
                        "direct": {"returncode": direct.returncode, "stdout": repr(direct.stdout), "stderr": repr(direct.stderr)},
                        "private": {"returncode": private.returncode, "stdout": repr(private.stdout), "stderr": repr(private.stderr)}}))
                if hashlib.sha256(checker.read_bytes()).hexdigest() != before:
                    raise RuntimeError("source checker changed during comparison: " + context)
                rows.append({"context": context, "valid_request": valid,
                             "checker_sha256": before, "returncode": private.returncode,
                             "stdout_sha256": hashlib.sha256(private.stdout).hexdigest(),
                             "stderr_sha256": hashlib.sha256(private.stderr).hexdigest(),
                             "elapsed_seconds": time.monotonic() - started,
                             "comparison": "byte-identical"})
                print(json.dumps(rows[-1]), flush=True)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guest", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args()
    check(args.guest.resolve(), args.runtime.resolve())
