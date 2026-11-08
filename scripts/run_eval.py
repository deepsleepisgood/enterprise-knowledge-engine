"""Evaluation harness (BUILD_PLAN Phase 5, TEST_PLAN levels 5-6).

    python scripts/run_eval.py --split dev                  # full system (config D) on dev
    python scripts/run_eval.py --split all --config ablation  # A, B, C and D
    python scripts/run_eval.py --split dev --limit 20 --type conflict
    python scripts/run_eval.py --split dev --no-judge       # scenarios graded, judge skipped

Writes reports/eval_<date>_<split>.md, a per-question CSV and the cards (JSONL) per config.
Holdout: look at scores only, never at failures, until the freeze (TEST_PLAN section 3).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation import dataset  # noqa: E402
from evaluation.judge import calibration, write_template  # noqa: E402
from evaluation.run import Options, evaluate, summarise, write_report  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    ap.add_argument("--config", default="D", help="A, B, C, D or 'ablation' (all four)")
    ap.add_argument("--type", help="only this question type (scenario, conflict, ...)")
    ap.add_argument("--limit", type=int, help="first N questions after filtering")
    ap.add_argument("--no-judge", action="store_true", help="skip the LLM judge")
    ap.add_argument("--workers", type=int, default=3, help="questions in parallel")
    ap.add_argument("--today", default="2026-11-07", help="the date questions are asked on")
    ap.add_argument("--tenant", help="tenant id (default: TENANT_ID)")
    args = ap.parse_args()

    qs = dataset.select(dataset.with_split(dataset.load()), args.split)
    if args.type:
        qs = [q for q in qs if q.type == args.type]
    if args.limit:
        qs = qs[: args.limit]
    configs = ["A", "B", "C", "D"] if args.config == "ablation" else [args.config.upper()]
    print(f"{len(qs)} questions ({args.split}), configs {configs}")

    results = {}
    for c in configs:
        opt = Options(
            config=c,
            use_judge=not args.no_judge,
            today=date.fromisoformat(args.today),
            workers=args.workers,
            tenant=args.tenant,
        )
        results[c] = evaluate(qs, opt)
        s = summarise(results[c])
        print(
            f"config {c}: accuracy {s['accuracy']}, citations {s['citation_strict']}, "
            f"outdated (conflict) {s['outdated_conflict']}, p50 {s['latency_p50_s']}s"
        )

    extra = {"questions": len(qs), "today": args.today}
    if "D" in results:
        judged = {r["id"]: r["verdict"] for r in results["D"] if r["type"] != "scenario"}
        cal = calibration(judged)
        extra["judge calibration"] = cal or "not yet graded (eval/judge/hand_graded.csv)"
        made = write_template(results["D"])
        if made:
            print(f"wrote {made} answers to eval/judge/hand_graded.csv for hand grading")
    md = write_report(results, args.split, extra)
    print("report:", md)


if __name__ == "__main__":
    main()
