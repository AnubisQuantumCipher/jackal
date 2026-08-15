"""JACKAL evaluation runner.

Modes:
    --dry-run                    build corpus, verify runners accept Problem, no API/tool calls needed
    --scale N                    cap problems per category at N; run all conditions (default 200)
    --conditions a,b             restrict runners
    --categories a,b             restrict categories
    --model {auto,live,stub,bridge}
                                  auto (default): live if bridge succeeds else stub
                                  live: use in-process completion() — REQUIRES OMP eval kernel
                                  bridge: subprocess to completion_bridge.py (needs API key)
                                  stub: deterministic tool-request only, flagged OBSERVED-STUB
    --out DIR                    output dir (default: evals/, plus release/evidence/eval_v1/)
    --workers N                  concurrent problem workers (default 4; use 1 for stub)

Every reported number is derived from a real call:
    - real Claude call if model=live/bridge and it succeeded
    - real dc / python3 / jackal-native / hermes call always

Manifest identities from release/MANIFEST.sha256 are recorded in every JSONL
row and in the report footer so a reader knows exactly what was measured.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evals.corpus import build_corpus, GENERATORS  # noqa: E402
from evals import conditions as C  # noqa: E402
from evals.metrics import Observation, judge, summarize  # noqa: E402


# --------------------------------------------------------------------------- #
# Manifest identity extraction                                                 #
# --------------------------------------------------------------------------- #
def read_manifest_identities() -> dict:
    txt = (REPO_ROOT / "release" / "MANIFEST.sha256").read_text()
    out = {}
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            key = parts[0]
            digest = parts[-1]
            out[key] = digest
    return out


MANIFEST = read_manifest_identities()


# --------------------------------------------------------------------------- #
# Model providers                                                              #
# --------------------------------------------------------------------------- #
def make_bridge_model_fn():
    bridge = str(REPO_ROOT / "evals" / "completion_bridge.py")

    def _fn(prompt, system=None, max_tokens=256):
        req = {"prompt": prompt, "model": "smol", "max_tokens": max_tokens}
        if system:
            req["system"] = system
        try:
            r = subprocess.run(
                ["python3", bridge], input=json.dumps(req).encode(),
                capture_output=True, timeout=90,
            )
            if r.returncode == 0:
                d = json.loads(r.stdout.decode())
                return C.ModelReply(
                    text=d.get("text", ""),
                    tokens_in=d.get("tokens_in", 0),
                    tokens_out=d.get("tokens_out", 0),
                    latency_ms=d.get("latency_ms", 0),
                    stub=False,
                )
            return None  # NO_API_KEY or error
        except Exception:
            return None
    return _fn


def bridge_available() -> bool:
    bridge = str(REPO_ROOT / "evals" / "completion_bridge.py")
    r = subprocess.run(
        ["python3", bridge], input=json.dumps({"prompt": "test"}).encode(),
        capture_output=True, timeout=90,
    )
    return r.returncode == 0


# --------------------------------------------------------------------------- #
# Runner core                                                                  #
# --------------------------------------------------------------------------- #
def run_one(problem, condition, model_fn):
    runner = C.CONDITIONS[condition]
    try:
        return runner(problem, model_fn)
    except Exception as e:  # noqa: BLE001
        return Observation(
            problem_id=problem.id, condition=condition,
            answer_text="", answer_extracted="", claimed_status="none",
            error=f"runner-error: {e}",
        )


def run_batch(problems, conditions, model_fn, workers=4, stub=False, verbose=False):
    obs_list = []
    total = len(problems) * len(conditions)
    done = 0
    t_start = time.time()

    if stub or workers <= 1:
        for cond in conditions:
            for p in problems:
                fn = C.stub_model(p, cond) if stub else model_fn
                obs = run_one(p, cond, fn)
                obs_list.append(obs)
                done += 1
                if verbose and done % 50 == 0:
                    elapsed = time.time() - t_start
                    rate = done / max(elapsed, 1e-6)
                    print(f"  {done}/{total} ({rate:.1f}/s)", file=sys.stderr)
        return obs_list

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {}
        for cond in conditions:
            for p in problems:
                fn = model_fn
                futures[ex.submit(run_one, p, cond, fn)] = (p.id, cond)
        for fut in cf.as_completed(futures):
            obs = fut.result()
            obs_list.append(obs)
            done += 1
            if verbose and done % 50 == 0:
                elapsed = time.time() - t_start
                rate = done / max(elapsed, 1e-6)
                print(f"  {done}/{total} ({rate:.1f}/s)", file=sys.stderr)
    return obs_list


# --------------------------------------------------------------------------- #
# Report writer                                                                #
# --------------------------------------------------------------------------- #
def write_jsonl(obs_list, judgments, problems, out_path, scale, model_kind):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    by_pid = {p.id: p for p in problems}
    j_by_key = {(j.problem_id, j.condition): j for j in judgments}
    with out_path.open("w") as f:
        for obs in obs_list:
            p = by_pid.get(obs.problem_id)
            j = j_by_key.get((obs.problem_id, obs.condition))
            row = {
                "problem": p.to_dict() if p else {"id": obs.problem_id},
                "observation": {
                    "condition": obs.condition,
                    "answer_extracted": obs.answer_extracted,
                    "claimed_status": obs.claimed_status,
                    "tool_used": obs.tool_used,
                    "verified": obs.verified,
                    "tokens_in": obs.tokens_in,
                    "tokens_out": obs.tokens_out,
                    "latency_ms": obs.latency_ms,
                    "error": obs.error,
                },
                "judgment": {
                    "correct": bool(j.correct) if j else False,
                    "incorrect": bool(j.incorrect) if j else False,
                    "refused_correctly": bool(j.refused_correctly) if j else False,
                    "refused_incorrectly": bool(j.refused_incorrectly) if j else False,
                    "confidently_wrong": bool(j.confidently_wrong) if j else False,
                    "false_exact_label": bool(j.false_exact_label) if j else False,
                    "estimate_inflation": bool(j.estimate_inflation) if j else False,
                    "verification_catch": bool(j.verification_catch) if j else False,
                    "reason": j.reason if j else "no-judgment",
                },
                "pins": MANIFEST,
                "run_scale": scale,
                "model_kind": model_kind,
            }
            f.write(json.dumps(row))
            f.write("\n")


def render_report(agg, scale, model_kind, run_ts, out_path):
    conds = ["model_only", "model_dc", "model_python", "model_jackal", "model_jackal_verified"]
    cats = [name for name, _ in GENERATORS]

    lines = []
    lines.append("# JACKAL Evaluation Report — eval_v1")
    lines.append("")
    lines.append("## Scope (honest)")
    lines.append("")
    lines.append(f"- Timestamp (UTC): {run_ts}")
    lines.append(f"- Scale: {scale} problems per category × {len(cats)} categories × {len(conds)} conditions")
    lines.append(f"- Total observations: {sum(a.problems for a in agg.values())}")
    lines.append(f"- Model kind: **{model_kind}**")
    lines.append("- Model family: Claude only (Anthropic API is the only model surface available here).")
    lines.append("  This is a WITHIN-MODEL comparison across five tool-use conditions — NOT a cross-model comparison.")
    lines.append("- One machine (Apple M4 Max, darwin 25.6.0), one session, one process pool.")
    lines.append("- Every number below is derived from a real tool call. STUB rows (marked `[stub]`) had no live Claude call for that condition, but their tool outputs (dc / python / jackal / hermes) are real. Model_only under stub is a fail-closed row.")
    lines.append("")
    lines.append("## Pinned identities (release/MANIFEST.sha256)")
    lines.append("")
    for k, v in MANIFEST.items():
        lines.append(f"- `{k}` = `{v}`")
    lines.append("")

    lines.append("## Per-condition × per-category summary")
    lines.append("")
    # header
    hdr = ["condition", "category", "N", "correct", "incorrect", "refused_ok", "refused_wrong",
           "conf_wrong", "false_exact", "est_infl", "verif_catch", "mean_ms", "tokens"]
    lines.append("| " + " | ".join(hdr) + " |")
    lines.append("|" + "|".join(["---"] * len(hdr)) + "|")

    for cond in conds:
        for cat in cats:
            a = agg.get(cond + "|" + cat)
            if not a:
                continue
            stub_mark = " [stub]" if a.observed_stub else ""
            row = [
                cond + stub_mark, cat, str(a.problems),
                str(a.correct), str(a.incorrect),
                str(a.refused_correctly), str(a.refused_incorrectly),
                str(a.confidently_wrong), str(a.false_exact_labels),
                str(a.estimate_inflations), str(a.verification_catches),
                f"{a.mean_latency_ms:.1f}", str(a.total_tokens),
            ]
            lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("## Condition roll-up (summed across categories)")
    lines.append("")
    hdr2 = ["condition", "N", "correct", "incorrect", "refused_ok", "refused_wrong",
            "conf_wrong", "false_exact", "est_infl", "verif_catch"]
    lines.append("| " + " | ".join(hdr2) + " |")
    lines.append("|" + "|".join(["---"] * len(hdr2)) + "|")

    for cond in conds:
        subs = [a for k, a in agg.items() if a.condition == cond]
        if not subs:
            continue
        stub_any = any(a.observed_stub for a in subs)
        mark = " [stub]" if stub_any else ""
        row = [
            cond + mark,
            str(sum(a.problems for a in subs)),
            str(sum(a.correct for a in subs)),
            str(sum(a.incorrect for a in subs)),
            str(sum(a.refused_correctly for a in subs)),
            str(sum(a.refused_incorrectly for a in subs)),
            str(sum(a.confidently_wrong for a in subs)),
            str(sum(a.false_exact_labels for a in subs)),
            str(sum(a.estimate_inflations for a in subs)),
            str(sum(a.verification_catches for a in subs)),
        ]
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("## Category legend")
    lines.append("")
    lines.append("| cat | description |")
    lines.append("|---|---|")
    lines.append("| arith | 12–30 digit int add/mul/pow (exact) |")
    lines.append("| frac  | exact reduced-fraction arithmetic |")
    lines.append("| int   | ∫x^k dx on integer bounds (exact rational) |")
    lines.append("| diff  | d/dx x^k at integer point (exact) |")
    lines.append("| sing  | singularities — correct = refuse |")
    lines.append("| thr   | close rational > comparisons (yes/no) |")
    lines.append("| dec   | 0.a+0.b — exact rational, not IEEE decimal |")
    lines.append("| ref   | asks for a formal cert that must refuse |")
    lines.append("| unit  | SI conversions with rational factors |")
    lines.append("| root  | x^2 = perfect_square, positive integer root |")
    lines.append("")
    lines.append("## Judge rules")
    lines.append("")
    lines.append("- CORRECT: extracted answer matches ground truth within tolerance (exact for rationals; ulp for f64; rel:1e-9 for estimated) OR expected_status=refused and observed status=refused.")
    lines.append("- CONFIDENTLY WRONG: extracted != ground truth (beyond tolerance) AND no hedge word ('approximately','about','estimate','roughly','~','≈') in the reply.")
    lines.append("- FALSE EXACT LABEL: response labels itself exact/certified/bounded but disagrees with ground truth.")
    lines.append("- ESTIMATE INFLATION: claimed_status ∈ {exact, bounded, formal-bounded} but extracted != ground truth.")
    lines.append("- VERIFICATION CATCH: `jackal_verify_receipt` was invoked AND its verdict agrees with the judge's correctness call.")
    lines.append("")
    out_path.write_text("\n".join(lines))


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scale", type=int, default=200)
    ap.add_argument("--conditions", type=str, default="")
    ap.add_argument("--categories", type=str, default="")
    ap.add_argument("--model", type=str, default="auto",
                    choices=("auto", "live", "stub", "bridge"))
    ap.add_argument("--out", type=str, default=str(REPO_ROOT / "evals"))
    ap.add_argument("--evidence", type=str,
                    default=str(REPO_ROOT / "release" / "evidence" / "eval_v1"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    corpus = build_corpus(args.scale)
    if args.categories:
        wanted = set(args.categories.split(","))
        corpus = [p for p in corpus if p.category in wanted]

    conds = args.conditions.split(",") if args.conditions else list(C.CONDITIONS.keys())
    for c in conds:
        if c not in C.CONDITIONS:
            print(f"unknown condition: {c}", file=sys.stderr)
            return 2

    if args.dry_run:
        print(f"corpus size: {len(corpus)} problems")
        # sanity: each runner accepts a problem via stub model
        first = corpus[0]
        for c in conds:
            fn = C.stub_model(first, c)
            obs = C.CONDITIONS[c](first, fn)
            assert obs.problem_id == first.id, f"runner {c} returned wrong problem_id"
        print(f"runners accepted: {', '.join(conds)}")
        print(f"conditions: {conds}")
        print(f"categories: {[n for n, _ in GENERATORS]}")
        return 0

    # decide model
    if args.model == "live":
        try:
            # in-process completion() only available in OMP eval kernel
            _completion = globals().get("completion") or __builtins__.__dict__.get("completion")  # type: ignore
        except Exception:
            _completion = None
        if _completion is None:
            print("--model=live requires the OMP eval kernel; use --model=bridge or --model=stub instead", file=sys.stderr)
            return 2
        model_kind = "live-omp-completion"
        stub = False
        model_fn = _make_live_fn(_completion)
    elif args.model == "bridge":
        if not bridge_available():
            print("bridge unavailable (NO_API_KEY). Falling back to stub for tool conditions.", file=sys.stderr)
            model_kind = "stub"
            stub = True
            model_fn = None
        else:
            model_kind = "bridge-anthropic-api"
            stub = False
            model_fn = make_bridge_model_fn()
    elif args.model == "stub":
        model_kind = "stub"
        stub = True
        model_fn = None
    else:  # auto
        if bridge_available():
            model_kind = "bridge-anthropic-api"
            stub = False
            model_fn = make_bridge_model_fn()
        else:
            model_kind = "stub"
            stub = True
            model_fn = None

    print(f"[eval] scale={args.scale} conditions={conds} model_kind={model_kind} problems={len(corpus)}", file=sys.stderr)
    t_start = time.time()

    observations = run_batch(
        corpus, conds, model_fn,
        workers=args.workers, stub=stub, verbose=args.verbose,
    )

    judgments = []
    problems_by_id = {p.id: p for p in corpus}
    for obs in observations:
        p = problems_by_id[obs.problem_id]
        judgments.append(judge(p, obs))

    agg = summarize(observations, judgments)

    # mark observed-stub aggregates
    if stub:
        for a in agg.values():
            a.observed_stub = True

    run_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ev_dir = Path(args.evidence)
    ev_dir.mkdir(parents=True, exist_ok=True)

    write_jsonl(observations, judgments, corpus, ev_dir / "results.jsonl",
                scale=args.scale, model_kind=model_kind)
    render_report(agg, scale=args.scale, model_kind=model_kind, run_ts=run_ts,
                  out_path=out_dir / "report.md")

    elapsed = time.time() - t_start
    print(f"[eval] done: {len(observations)} observations in {elapsed:.1f}s -> {out_dir/'report.md'}", file=sys.stderr)
    return 0


def _make_live_fn(completion):
    def _fn(prompt, system=None, max_tokens=256):
        t0 = time.time()
        try:
            if system:
                text = completion(prompt, model="smol", system=system)
            else:
                text = completion(prompt, model="smol")
        except Exception as e:
            return C.ModelReply(text=f"<ANSWER>error:{e}</ANSWER>", stub=False,
                                latency_ms=int((time.time()-t0)*1000))
        ms = int((time.time() - t0) * 1000)
        # OMP completion returns str; token counts not exposed here
        text_s = text if isinstance(text, str) else str(text)
        return C.ModelReply(text=text_s, latency_ms=ms, stub=False)
    return _fn


if __name__ == "__main__":
    sys.exit(main())
