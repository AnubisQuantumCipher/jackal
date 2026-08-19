#!/usr/bin/env python3
"""JACKAL eval v2 runner — drives the pinned engine over evals/v2/corpus.py.

NO MODEL IS INVOKED BY THIS FILE.
=================================
This runner contains no model API client, no network call, and no credential
read. It executes one thing: the compiled JACKAL engine, as a subprocess, with
the argv recorded on each corpus item. Read that as a hard limit on what the
numbers coming out of here can mean:

  * `--mode forced` is a full measurement. The harness itself calls the engine
    for every item, so `verifier_use_rate` in forced mode measures the harness's
    own behaviour and is 1.0 over the eligible items by construction. It is
    reported because the protocol names it, not because it discriminates between
    builds. The metrics that actually discriminate in forced mode are
    `accuracy`, `refusal_precision`, `refusal_recall`,
    `false_strong_claim_rate`, `silent_downgrade_count` and the two latencies.

  * `--mode autonomous` asks a different question: when a model is free to
    answer from its own weights, does it reach for the verifier at all? That is a
    property of a model session, and this file cannot observe one. In autonomous
    mode `invoked_tool` is therefore taken ONLY from a `--transcript` file
    supplied by whoever ran the live session. With no transcript every
    `invoked_tool` is the empty string and `verifier_use_rate` reads 0.0 — that
    zero is "no transcript was supplied", NOT "the model declined to verify".
    An autonomous `verifier_use_rate` without a transcript is not a measurement
    of any model and must not be reported as one.

Engine identity is recorded in the results file (compiler pin path + sha256,
`jackal_calc.anb` sha256, compiled artifact sha256) so a receipt binds to the
build it was taken on.

Refusal detection: a non-zero exit code, or `ANUBIS_PANIC` anywhere in stdout or
stderr, is `refused: true`. The engine surfaces fail-closed refusals through the
runtime panic channel (its own `maturity` output says so:
`class=refused behavior=fail-closed-nonzero-exit-with-named-reason`).

Usage
-----
  python3 evals/v2/runner.py --mode forced --limit 8 --out /tmp/results.json
  python3 evals/v2/metrics.py --verify-receipts /tmp/results.json
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus import aggregate_digest, item_digest, load_corpus  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ENGINE_SOURCE = REPO_ROOT / "jackal_calc.anb"
DEFAULT_PIN = Path.home() / "anubis-lang" / "vm" / "pins" / "anubis-a733565f237d"
DEFAULT_BUILD_DIR = Path("/tmp/jackal-eval-v2-build")

# raw_stdout is capped so a results file stays readable; the sha256 of the FULL
# stdout is always recorded, so the receipt still binds the untruncated bytes.
RAW_STDOUT_CAP = 4096

STATUS_RE = re.compile(r"^status[= ]([A-Za-z][A-Za-z0-9-]*)", re.MULTILINE)
PANIC_RE = re.compile(r"ANUBIS_PANIC:\s*(.*)")
ENCLOSURE_RE = re.compile(r"-enclosure=\[([^,\]]+),([^\]]+)\]")


# ---------------------------------------------------------------------------
# engine plumbing — built ONCE, reused for every item
# ---------------------------------------------------------------------------


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_compiler():
    override = os.environ.get("ANUBIS_BIN")
    if override:
        p = Path(override)
        if not (p.is_file() and os.access(p, os.X_OK)):
            raise RuntimeError(f"ANUBIS_BIN={override} is not an executable file")
        return p
    if DEFAULT_PIN.is_file() and os.access(DEFAULT_PIN, os.X_OK):
        return DEFAULT_PIN
    raise RuntimeError(
        f"no Anubis compiler: {DEFAULT_PIN} is missing and ANUBIS_BIN is unset"
    )


def build_engine(build_dir, force=False, timeout=1800):
    """Compile jackal_calc.anb once; return (artifact_path, identity_dict).

    The pinned compiler's `run` subcommand writes the native artifact to
    `<build_dir>/anubis_run`. Every corpus item then execs that artifact
    directly, so the ~10 s compile is paid once per run and not 48 times.
    """
    compiler = resolve_compiler()
    if not ENGINE_SOURCE.is_file():
        raise RuntimeError(f"engine source missing: {ENGINE_SOURCE}")
    build_dir = Path(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    artifact = build_dir / "anubis_run"

    src_mtime = ENGINE_SOURCE.stat().st_mtime
    stale = (
        force
        or not artifact.is_file()
        or not os.access(artifact, os.X_OK)
        or artifact.stat().st_mtime < src_mtime
    )
    if stale:
        proc = subprocess.run(
            [
                str(compiler),
                "run",
                str(ENGINE_SOURCE),
                "--out",
                str(build_dir),
                "--",
                "maturity",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=timeout,
        )
        if proc.returncode != 0 or not artifact.is_file():
            raise RuntimeError(
                "engine build failed rc=%s\n--- stdout tail ---\n%s\n"
                "--- stderr tail ---\n%s"
                % (proc.returncode, proc.stdout[-3000:], proc.stderr[-3000:])
            )
        if "class=exact" not in proc.stdout:
            raise RuntimeError(
                f"engine build produced unexpected warm output: {proc.stdout[:400]!r}"
            )
        built = "compiled"
    else:
        built = "reused"

    identity = {
        "compiler_path": str(compiler),
        "compiler_sha256": _sha256_file(compiler),
        "engine_source": str(ENGINE_SOURCE.relative_to(REPO_ROOT)),
        "engine_source_sha256": _sha256_file(ENGINE_SOURCE),
        "artifact_path": str(artifact),
        "artifact_sha256": _sha256_file(artifact),
        "build": built,
    }
    return artifact, identity


def invoke(artifact, argv, timeout=300):
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [str(artifact)] + [str(a) for a in argv],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=timeout,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return proc.returncode, proc.stdout, proc.stderr, elapsed_ms
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return 124, "", f"ANUBIS_PANIC: harness timeout after {timeout}s", elapsed_ms


# ---------------------------------------------------------------------------
# scoring — reads bytes, never substitutes an answer
# ---------------------------------------------------------------------------


def parse_status(stdout):
    m = STATUS_RE.search(stdout)
    return m.group(1) if m else None


def parse_refusal_reason(stdout, stderr):
    for blob in (stderr, stdout):
        m = PANIC_RE.search(blob or "")
        if m:
            return m.group(1).strip()
    return None


def _as_fraction(text):
    text = text.strip()
    try:
        return Fraction(text)
    except (ValueError, ZeroDivisionError):
        return Fraction(text.replace("_", ""))


def score(item, exit_code, stdout, stderr):
    """Return (passed, refused, reason, notes). Pure byte inspection."""
    exp = item["expected"]
    reason = parse_refusal_reason(stdout, stderr)
    refused = exit_code != 0 or reason is not None
    notes = []

    if exp.get("refused"):
        if not refused:
            notes.append("expected a fail-closed refusal, engine returned success")
            return False, refused, reason, notes
        want = exp.get("reason_contains")
        if want and want not in (reason or ""):
            notes.append(f"refusal reason missing {want!r}; got {reason!r}")
            return False, refused, reason, notes
        return True, refused, reason, notes

    if refused:
        notes.append(f"unexpected refusal (exit={exit_code}, reason={reason!r})")
        return False, refused, reason, notes

    ok = True
    got_status = parse_status(stdout)
    want_status = exp.get("status", "__absent__")
    if want_status != "__absent__" and got_status != want_status:
        ok = False
        notes.append(f"status: want {want_status!r}, got {got_status!r}")

    if "stdout_equals" in exp and stdout.strip() != exp["stdout_equals"]:
        ok = False
        notes.append(
            f"stdout: want {exp['stdout_equals']!r}, got {stdout.strip()[:200]!r}"
        )

    for needle in exp.get("stdout_contains", ()):
        if needle not in stdout:
            ok = False
            notes.append(f"stdout missing {needle!r}")

    if "encloses" in exp:
        m = ENCLOSURE_RE.search(stdout)
        if not m:
            ok = False
            notes.append("no *-enclosure=[lo,hi] token in stdout")
        else:
            try:
                lo, hi = _as_fraction(m.group(1)), _as_fraction(m.group(2))
                want_lo = _as_fraction(exp["encloses"][0])
                want_hi = _as_fraction(exp["encloses"][1])
            except (ValueError, ZeroDivisionError) as exc:
                ok = False
                notes.append(f"unparseable enclosure endpoints: {exc}")
            else:
                if lo > want_lo or hi < want_hi:
                    ok = False
                    notes.append(
                        f"enclosure [{float(lo)!r},{float(hi)!r}] does not contain "
                        f"[{float(want_lo)!r},{float(want_hi)!r}]"
                    )
    return ok, refused, reason, notes


# ---------------------------------------------------------------------------
# transcript (autonomous mode only)
# ---------------------------------------------------------------------------


def load_transcript(path):
    """{item_id: invoked_tool} from a live-session transcript supplied by a human.

    Accepted shapes: {"item_id": "tool", ...} or
    [{"item_id": ..., "invoked_tool": ...}, ...].
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "items" in payload:
        payload = payload["items"]
    if isinstance(payload, dict):
        return {str(k): str(v or "") for k, v in payload.items()}
    if isinstance(payload, list):
        return {
            str(e["item_id"]): str(e.get("invoked_tool") or "")
            for e in payload
            if isinstance(e, dict) and "item_id" in e
        }
    raise ValueError(f"{path}: unrecognised transcript shape")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def run(mode, limit=None, build_dir=DEFAULT_BUILD_DIR, transcript=None, force_build=False):
    items = load_corpus()
    artifact, identity = build_engine(build_dir, force=force_build)
    selected = items if limit is None else items[:limit]
    tmap = load_transcript(transcript) if transcript else {}

    records = []
    for item in selected:
        exit_code, stdout, stderr, latency_ms = invoke(artifact, item["argv"])
        passed, refused, reason, notes = score(item, exit_code, stdout, stderr)

        if mode == "forced":
            invoked_tool = f"jackal_calc.anb:{item['argv'][0]}"
        else:
            invoked_tool = tmap.get(item["item_id"], "")

        full = stdout
        records.append(
            {
                "item_id": item["item_id"],
                "mode": mode,
                "invoked_tool": invoked_tool,
                "raw_stdout": full[:RAW_STDOUT_CAP],
                "parsed_status": parse_status(full),
                "passed": bool(passed),
                "refused": bool(refused),
                "latency_ms": round(latency_ms, 3),
                # --- beyond the required fields, so the receipt is self-contained
                "category": item["category"],
                "argv": item["argv"],
                "item_digest": item_digest(item),
                "exit_code": exit_code,
                "raw_stdout_truncated": len(full) > RAW_STDOUT_CAP,
                "raw_stdout_len": len(full),
                "raw_stdout_sha256": hashlib.sha256(full.encode("utf-8")).hexdigest(),
                "raw_stderr": stderr[:RAW_STDOUT_CAP],
                "refusal_reason": reason,
                "failure_notes": notes,
            }
        )

    results = {
        "schema": "jackal-eval-v2-results-v1",
        "mode": mode,
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "corpus_item_count": len(items),
        "corpus_aggregate_digest": aggregate_digest(items),
        "items_run": len(selected),
        "limit": limit,
        "engine_identity": identity,
        "transcript_path": str(transcript) if transcript else None,
        "model_invoked": False,
        "verifier_use_rate_caveat": (
            "forced: invoked_tool is set by the harness for every item, so "
            "verifier_use_rate is 1.0 by construction and measures the harness. "
            "autonomous: invoked_tool comes only from --transcript; with no "
            "transcript the 0.0 means 'no transcript supplied', not 'the model "
            "declined to verify'. No model API is called by this runner."
        ),
        "records": records,
    }
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="JACKAL eval v2 runner (no model API)")
    ap.add_argument("--mode", choices=("forced", "autonomous"), required=True)
    ap.add_argument("--limit", type=int, default=None, help="run the first N items")
    ap.add_argument("--out", required=True, help="results JSON path")
    ap.add_argument("--build-dir", default=str(DEFAULT_BUILD_DIR))
    ap.add_argument(
        "--transcript",
        default=None,
        help="autonomous mode only: JSON map of item_id -> invoked_tool captured "
        "from a live model session by a human",
    )
    ap.add_argument("--force-build", action="store_true")
    args = ap.parse_args(argv)

    if args.limit is not None and args.limit <= 0:
        ap.error("--limit must be positive")
    if args.transcript and args.mode != "autonomous":
        ap.error("--transcript is only meaningful with --mode autonomous")

    try:
        results = run(
            args.mode,
            limit=args.limit,
            build_dir=args.build_dir,
            transcript=args.transcript,
            force_build=args.force_build,
        )
    except RuntimeError as exc:
        print(f"RUNNER_FAIL {exc}", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", "utf-8")

    recs = results["records"]
    passed = sum(1 for r in recs if r["passed"])
    refused = sum(1 for r in recs if r["refused"])
    print(f"mode: {results['mode']}")
    print(f"engine build: {results['engine_identity']['build']}")
    print(f"artifact_sha256: {results['engine_identity']['artifact_sha256']}")
    print(f"engine_source_sha256: {results['engine_identity']['engine_source_sha256']}")
    print(f"corpus_aggregate_digest: {results['corpus_aggregate_digest']}")
    print(f"items_run: {len(recs)} of {results['corpus_item_count']}")
    print(f"passed: {passed}  failed: {len(recs) - passed}  refused: {refused}")
    print("model_invoked: False")
    for r in recs:
        flag = "PASS" if r["passed"] else "FAIL"
        print(f"  {flag} {r['item_id']} status={r['parsed_status']} "
              f"exit={r['exit_code']} {r['latency_ms']}ms")
        for note in r["failure_notes"]:
            print(f"       ! {note}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
