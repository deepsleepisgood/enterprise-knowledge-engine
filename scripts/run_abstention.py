"""Abstention set (TEST_PLAN level 8): questions the corpus does not cover must not be answered.

Each question in eval/abstain.csv goes through the normal answer pipeline. A question passes
when the engine does not answer it (status other than answered/provisional) and routes it to
one of the roles listed for it. Target: at least 90% pass.

    python scripts/run_abstention.py            # uses DATABASE_URL and the configured LLM

Asks as user `eval-abstain` (left out of analytics and answer recall). Writes
reports/abstention_<date>.md and .csv.
"""

from __future__ import annotations

import csv
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.answer.pipeline import ask  # noqa: E402

ANSWERED = {"answered", "provisional"}


def main() -> None:
    rows = list(csv.DictReader((ROOT / "eval" / "abstain.csv").open(encoding="utf-8")))
    results = []
    for r in rows:
        t0 = time.perf_counter()
        try:
            card = ask(r["question"], user_id="eval-abstain")
            err = ""
        except Exception as exc:  # report, keep going
            card, err = {}, f"{type(exc).__name__}: {exc}"[:200]
        secs = time.perf_counter() - t0
        status = card.get("status", "error")
        route = (card.get("route_to") or {}).get("role", "")
        reason = (card.get("route_to") or {}).get("reason", "")
        said = ((card.get("rule") or {}).get("text") or "").replace("\n", " ")
        ok_routes = [x.strip() for x in r["acceptable_routes"].split("|")]
        abstained = status not in ANSWERED and not err
        passed = abstained and route in ok_routes
        results.append(
            {
                **r,
                "status": status,
                "route": route,
                "reason": reason,
                "answer_text": said[:300],
                "abstained": abstained,
                "route_ok": route in ok_routes,
                "pass": passed,
                "seconds": round(secs, 1),
                "error": err,
            }
        )
        mark = "PASS" if passed else ("abstained, other route" if abstained else "FAIL")
        print(f"{r['id']} {mark:22} {status:16} -> {route or '-'} ({secs:.0f} s)", flush=True)

    n = len(results)
    abst = sum(x["abstained"] for x in results)
    passed = sum(x["pass"] for x in results)
    out = ROOT / "reports" / f"abstention_{date.today():%Y%m%d}"
    with out.with_suffix(".csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0]))
        w.writeheader()
        w.writerows(results)
    lines = [
        f"# Abstention set — {date.today():%d %b %Y}",
        "",
        f"{n} questions the corpus does not cover (`eval/abstain.csv`). Target: at least 90% "
        "not answered and routed to a sensible role.",
        "",
        f"- **Not answered (abstained):** {abst}/{n} ({abst / n:.0%})",
        f"- **Abstained and routed to an acceptable role (pass):** {passed}/{n} ({passed / n:.0%})",
        f"- **Answered anyway (false answers):** {n - abst}/{n}",
        "",
        "| id | category | question | status | routed to | pass |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for x in results:
        lines.append(
            f"| {x['id']} | {x['category']} | {x['question']} | {x['status']} | "
            f"{x['route'] or '—'} | {'PASS' if x['pass'] else 'FAIL'} |"
        )
    bad = [x for x in results if not x["pass"]]
    if bad:
        lines += ["", "## Not passed", ""]
        for x in bad:
            lines.append(
                f"- **{x['id']}** {x['question']} — status `{x['status']}`, routed to "
                f"{x['route'] or 'nobody'} (acceptable: {x['acceptable_routes']})"
                + (f"; said: “{x['answer_text']}”" if x["answer_text"] else "")
                + (f"; error: {x['error']}" if x["error"] else "")
            )
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"abstained {abst}/{n}, pass {passed}/{n}; report: {out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
