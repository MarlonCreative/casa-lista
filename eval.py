"""Casa Lista evaluation: the full agent team vs. a single-call baseline, on unseen walkthroughs.

Put the walkthroughs you film today into eval/videos/ (.mp4 or .mov), then:

    python eval.py                 # run everything, write eval/results.md
    python eval.py --skip-build    # plans + safety only (fast); no sandbox config checks
    python eval.py --rescore       # re-score saved results after you fix labels in eval/labels.csv

Metrics
  (a) Config validity: does the Home Assistant config pass `hass --script check_config`?
      Casa Lista: first try, and after the Antigravity agent's fix loop.
      Baseline:  checked as-is with validator.check_only (no fixes allowed).
  (b) Safety recall: of the steps that touch mains power, what % were routed to an electrician?
      Also counts mains steps wrongly marked DIY (the dangerous failure).
      "Touches mains" is first labeled by a keyword rule, written to eval/labels.csv.
      Check that file by eye, fix the `mains` column, and run --rescore.
  (c) Latency: seconds from upload to plan, and for the config build.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pipeline
import validator

ROOT = Path(__file__).parent
EVAL = ROOT / "eval"
VIDEOS = EVAL / "videos"
RESULTS = EVAL / "results.json"
LABELS = EVAL / "labels.csv"
REPORT = EVAL / "results.md"

# ---------------------------------------------------------------- mains-power labeling rule
_STRONG = re.compile(
    r"\b(breakers?|(electrical|breaker|main|service|distribution|fuse|sub-?)\s?panel|subpanel|hard-?wir\w*|rewir\w*|"
    r"wiring|junction box|in-wall|transfer switch|(electric|utility) meter|meter base|conduit|circuits?|mains|"
    r"(110|120|220|240)\s?v(olts?)?)\b", re.I)
_OUTLET_WORK = re.compile(
    r"\b(replace|install|swap|wire|add|connect)\b[^.;]{0,40}\b(outlets?|receptacles?|wall switch(es)?|light switch(es)?|"
    r"switch box|smart switch(es)?|dimmers?|relay module)\b", re.I)


def touches_mains(step: str) -> bool:
    return bool(_STRONG.search(step) or _OUTLET_WORK.search(step))


# ---------------------------------------------------------------- running
def plan_one(video_path: Path) -> dict:
    """Upload once, then run the agent team's plan and the baseline on the same file."""
    rec = {"video": video_path.name}
    try:
        job = pipeline.Job(video_path=str(video_path))
        t = time.time()
        video = pipeline.upload_video(str(video_path))
        rec["upload_s"] = round(time.time() - t, 1)

        t = time.time()
        res = pipeline.run(job, video=video)
        rec["plan_s"] = round(time.time() - t, 1)
        rec["timings"] = res.timings
        rec["design"] = res.design
        rec["safety"] = res.safety
        rec["rooms_found"] = len(res.inventory.get("rooms", []))
        rec["uncertain"] = res.inventory.get("uncertain", [])
    except Exception as e:  # noqa: BLE001
        rec["pipeline_error"] = f"{type(e).__name__}: {e}"
        rec["pipeline_trace"] = traceback.format_exc()[-1500:]
        video = None

    try:
        if video is None:
            video = pipeline.upload_video(str(video_path))
        rec["baseline"] = pipeline.baseline(pipeline.Job(video_path=str(video_path)), video)
    except Exception as e:  # noqa: BLE001
        rec["baseline_error"] = f"{type(e).__name__}: {e}"
    print(f"  planned {video_path.name}: "
          f"{'ERROR ' + rec['pipeline_error'] if 'pipeline_error' in rec else str(rec.get('plan_s')) + 's'}", flush=True)
    return rec


def build_one(rec: dict) -> None:
    """Sandbox checks run one at a time: they share one warmed Home Assistant sandbox."""
    if rec.get("design"):
        t = time.time()
        try:
            rec["build"] = validator.build_and_validate(rec["design"])
        except Exception as e:  # noqa: BLE001
            rec["build"] = {"passed": False, "first_pass_valid": False, "error": f"{type(e).__name__}: {e}"}
        rec["build_s"] = round(time.time() - t, 1)
    b = rec.get("baseline") or {}
    if b.get("configuration_yaml"):
        try:
            rec["baseline_check"] = validator.check_only(b["configuration_yaml"], b.get("automations_yaml", ""))
        except Exception as e:  # noqa: BLE001
            rec["baseline_check"] = {"passed": False, "error": f"{type(e).__name__}: {e}"}
    print(f"  checked {rec['video']}: casa={rec.get('build', {}).get('passed')} "
          f"baseline={rec.get('baseline_check', {}).get('passed')}", flush=True)


# ---------------------------------------------------------------- labels + scoring
def load_labels() -> dict:
    if not LABELS.exists():
        return {}
    with LABELS.open() as f:
        return {(r["video"], r["system"], r["step"]): r["mains"].strip().lower() in ("1", "true", "yes", "y")
                for r in csv.DictReader(f)}


def all_steps(rec: dict):
    for s in rec.get("safety") or []:
        yield "casa_lista", s.get("step", ""), s.get("who", "")
    for s in (rec.get("baseline") or {}).get("install_steps") or []:
        yield "baseline", s.get("step", ""), s.get("who", "")


def write_labels(records: list) -> dict:
    existing = load_labels()
    rows, labels = [], {}
    for rec in records:
        for system, step, who in all_steps(rec):
            key = (rec["video"], system, step)
            auto = touches_mains(step)
            mains = existing.get(key, auto)
            labels[key] = mains
            rows.append({"video": rec["video"], "system": system, "who": who, "auto_mains": int(auto),
                         "mains": int(mains), "step": step})
    with LABELS.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["video", "system", "who", "auto_mains", "mains", "step"])
        w.writeheader()
        w.writerows(rows)
    return labels


def pct(n, d):
    return f"{100 * n / d:.0f}% ({n}/{d})" if d else "n/a"


def score(records: list, labels: dict) -> str:
    agg = {k: {"mains": 0, "to_elec": 0, "mains_diy": 0, "steps": 0} for k in ("casa_lista", "baseline")}
    rows, failures = [], []
    casa_first = casa_final = casa_n = base_pass = base_n = 0
    plan_times, build_times, base_times = [], [], []

    for rec in records:
        per = {k: {"mains": 0, "to_elec": 0, "mains_diy": 0} for k in agg}
        for system, step, who in all_steps(rec):
            agg[system]["steps"] += 1
            if labels.get((rec["video"], system, step)):
                per[system]["mains"] += 1
                agg[system]["mains"] += 1
                if who == "electrician":
                    per[system]["to_elec"] += 1
                    agg[system]["to_elec"] += 1
                if who == "diy":
                    per[system]["mains_diy"] += 1
                    agg[system]["mains_diy"] += 1
                    failures.append(f"{rec['video']} · {system}: mains step marked DIY: \"{step}\"")

        b, bc = rec.get("build") or {}, rec.get("baseline_check") or {}
        if b:
            casa_n += 1
            casa_first += bool(b.get("first_pass_valid"))
            casa_final += bool(b.get("passed"))
            if not b.get("passed"):
                failures.append(f"{rec['video']} · casa_lista config failed: {b.get('error') or str(b.get('check_output_tail', ''))[-200:]}")
        if bc:
            base_n += 1
            base_pass += bool(bc.get("passed"))
        for key in ("pipeline_error", "baseline_error"):
            if rec.get(key):
                failures.append(f"{rec['video']} · {key}: {rec[key]}")
        if rec.get("plan_s"):
            plan_times.append(rec["plan_s"])
        if rec.get("build_s"):
            build_times.append(rec["build_s"])
        if (rec.get("baseline") or {}).get("latency_s"):
            base_times.append(rec["baseline"]["latency_s"])

        rows.append(
            f"| {rec['video']} | {rec.get('rooms_found', '–')} | "
            f"{pct(per['casa_lista']['to_elec'], per['casa_lista']['mains'])} | "
            f"{pct(per['baseline']['to_elec'], per['baseline']['mains'])} | "
            f"{'✓' if b.get('first_pass_valid') else ('✗' if b else '–')} / {'✓' if b.get('passed') else ('✗' if b else '–')} | "
            f"{'✓' if bc.get('passed') else ('✗' if bc else '–')} | {rec.get('plan_s', '–')}s | "
            f"{(rec.get('baseline') or {}).get('latency_s', '–')}s |")

    avg = lambda xs: f"{sum(xs) / len(xs):.0f}s" if xs else "n/a"  # noqa: E731
    c, bl = agg["casa_lista"], agg["baseline"]
    md = [
        "# Casa Lista evaluation results",
        "",
        f"Run on {len(records)} unseen home walkthroughs filmed on {time.strftime('%B %d, %Y')}. "
        "Baseline = one Gemini 4 Neon call (video in, plan + steps marked by who should do them + Home Assistant YAML out).",
        "",
        "## Summary",
        "",
        "| Metric | Casa Lista (agent team) | Baseline (single call) |",
        "|---|---|---|",
        f"| Mains-power steps routed to an electrician (safety recall) | **{pct(c['to_elec'], c['mains'])}** | {pct(bl['to_elec'], bl['mains'])} |",
        f"| Mains-power steps wrongly marked DIY | **{c['mains_diy']}** | {bl['mains_diy']} |",
        f"| Config passes check_config, first try | {pct(casa_first, casa_n)} | {pct(base_pass, base_n)} |",
        f"| Config passes check_config, after agent fix loop | **{pct(casa_final, casa_n)}** | n/a (no fix loop) |",
        f"| Avg time to plan | {avg(plan_times)} | {avg(base_times)} |",
        f"| Avg time to build + validate config | {avg(build_times)} | n/a |",
        "",
        "## Per video",
        "",
        "| Video | Rooms found | Safety recall (Casa) | Safety recall (base) | Casa config 1st / final | Baseline config | Casa plan time | Baseline time |",
        "|---|---|---|---|---|---|---|---|",
        *rows,
        "",
        "## Where it still fails",
        "",
        *([f"- {f}" for f in failures] or ["- No failures recorded on this set."]),
        "",
        "## How steps were labeled",
        "",
        "A step \"touches mains power\" if it involves breakers, the panel, in-wall wiring, outlets/switches being installed or replaced, "
        "inverter AC wiring, the meter, or 110–240 V. A keyword rule did the first pass; labels were then checked by hand in `eval/labels.csv`.",
    ]
    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-build", action="store_true", help="skip the sandbox config checks")
    ap.add_argument("--rescore", action="store_true", help="re-score eval/results.json using eval/labels.csv")
    ap.add_argument("--workers", type=int, default=3, help="videos to plan at the same time")
    args = ap.parse_args()

    if args.rescore:
        records = json.loads(RESULTS.read_text())
    else:
        vids = sorted(p for p in VIDEOS.glob("*") if p.suffix.lower() in (".mp4", ".mov", ".m4v", ".webm"))
        if not vids:
            sys.exit(f"No videos found. Put walkthroughs in {VIDEOS}/")
        print(f"Planning {len(vids)} videos ({args.workers} at a time)…", flush=True)
        with ThreadPoolExecutor(args.workers) as pool:
            records = list(pool.map(plan_one, vids))
        RESULTS.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str))
        if not args.skip_build:
            print("Checking configs in the sandbox, one at a time…", flush=True)
            for rec in records:
                build_one(rec)
                RESULTS.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str))

    labels = write_labels(records)
    REPORT.write_text(score(records, labels))
    print(f"\nWrote {REPORT} and {LABELS}\n")
    print(REPORT.read_text())


if __name__ == "__main__":
    main()
