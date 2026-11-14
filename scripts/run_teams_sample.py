"""Ask the engine a sample of the questions processors really asked in Teams.

Reads `teams_questions` from the operations workbook (data/ops/PS-07_ap_operations.xlsx), asks
the chosen messages through the normal answer pipeline as user `eval-teams` (left out of
analytics and recall), and writes every answer card to reports/teams_sample_<date>.jsonl for
review. The sheet has no gold answers, only where a correct colleague answer came from, so the
cards are judged by hand against the documents.

    python scripts/run_teams_sample.py M51441 M50114 ...
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.answer.pipeline import ask  # noqa: E402

WORKBOOK = ROOT / "data" / "ops" / "PS-07_ap_operations.xlsx"


def load(ids: list[str]) -> list[dict]:
    ws = openpyxl.load_workbook(WORKBOOK, read_only=True)["teams_questions"]
    rows = list(ws.iter_rows(values_only=True))
    head = rows[0]
    by_id = {r[0]: dict(zip(head, r, strict=True)) for r in rows[1:]}
    return [by_id[i] for i in ids]


def main() -> None:
    ids = sys.argv[1:]
    out = ROOT / "reports" / f"teams_sample_{date.today():%Y%m%d}.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for q in load(ids):
            t0 = time.perf_counter()
            try:
                card, err = ask(q["question_text"], user_id="eval-teams"), ""
            except Exception as exc:  # report, keep going
                card, err = {}, f"{type(exc).__name__}: {exc}"[:300]
            row = {
                "id": q["message_id"],
                "topic": q["topic"],
                "question": q["question_text"],
                "colleague_correct": q["answer_consistent_with_current_rules"],
                "source_if_correct": q["answer_source_if_correct"],
                "seconds": round(time.perf_counter() - t0, 1),
                "error": err,
                "card": card,
            }
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            f.flush()
            print(
                f"{q['message_id']} {card.get('status', 'error'):12} {card.get('route', '-'):24} "
                f"{row['seconds']:5.1f}s {q['topic']}",
                flush=True,
            )
    print(f"cards: {out}")


if __name__ == "__main__":
    main()
