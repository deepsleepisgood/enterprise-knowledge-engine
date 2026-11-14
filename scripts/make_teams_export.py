"""Build synthetic/teams_export.json: test data for the Teams chat-export connector.

The operations workbook's `teams_questions` sheet records real questions processors asked in
Teams (text, time, asker), but not the replies. This script turns a stratified sample of them
(2 per topic, fixed seed) into posts in the Microsoft Graph chatMessage shape, with the asker's
name and role from the `employees` sheet, and adds six hand-written threads that exercise the
other triage routes. The hand-written ones are synthetic and say so in their ids (`SYN-…`):

    SYN-TIP     a colleague's supplier habit (tacit_tip: extracted, held for review)
    SYN-CLAIM   a processor saying a tolerance changed (rule_change: held, not applied)
    SYN-LUNCH   social chat (noise: nothing extracted)
    SYN-Q       a question with a colleague's reply (question: recorded, not answered again)
    SYN-OOO     an out-of-office reply (noise)
    SYN-REMIND  a team lead restating a rule (rule_change: extracted, governed)

    python scripts/make_teams_export.py            # writes synthetic/teams_export.json
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "data" / "ops" / "PS-07_ap_operations.xlsx"
OUT = ROOT / "synthetic" / "teams_export.json"
SEED = 7
PER_TOPIC = 2


def _rows(ws) -> list[dict]:  # type: ignore[no-untyped-def]
    rows = list(ws.iter_rows(values_only=True))
    return [dict(zip(rows[0], r, strict=True)) for r in rows[1:]]


def _msg(mid: str, at: datetime, name: str, role: str, html: str, reply_to: str | None = None):  # type: ignore[no-untyped-def]
    return {
        "id": mid,
        "replyToId": reply_to,
        "messageType": "message",
        "createdDateTime": at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "from": {"user": {"displayName": name, "jobTitle": role}},
        "body": {"contentType": "html", "content": html},
        "channelIdentity": {"teamId": "ap-ops", "channelId": "ap-questions"},
    }


def build() -> dict:
    wb = openpyxl.load_workbook(WORKBOOK, read_only=True)
    people = {r["employee_id"]: r for r in _rows(wb["employees"])}
    questions = _rows(wb["teams_questions"])
    by_topic: dict[str, list[dict]] = defaultdict(list)
    for q in questions:
        by_topic[q["topic"]].append(q)
    rng = random.Random(SEED)
    picked = [q for t in sorted(by_topic) for q in rng.sample(by_topic[t], k=PER_TOPIC)]

    msgs = []
    for q in sorted(picked, key=lambda q: q["asked_at"]):
        who = people.get(q["asker_employee_id"]) or {}
        at = q["asked_at"].replace(tzinfo=UTC)
        msgs.append(
            _msg(
                q["message_id"],
                at,
                who.get("name") or q["asker_employee_id"],
                who.get("role") or "",
                f"<p>{q['question_text']}</p>",
            )
        )

    base = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
    senior, lead, proc = "Kavya Menon", "Rohan Gupta", "Sneha Iyer"
    synthetic = [
        _msg(
            "SYN-TIP",
            base,
            senior,
            "Senior Processor",
            "<p>Heads-up for anyone on the Pharma desk: when a payment is late, "
            "<b>Balaji Logistics</b> re-sends the same invoice with /A added to the number. "
            "Check for the original before you post it.</p>",
        ),
        _msg(
            "SYN-TIP-R1",
            base + timedelta(minutes=12),
            proc,
            "AP Processor",
            "<p>Thanks! Saw one of those last week.</p>",
            reply_to="SYN-TIP",
        ),
        _msg(
            "SYN-CLAIM",
            base + timedelta(hours=2),
            proc,
            "AP Processor",
            "<p>FYI the price tolerance is 2% again for all clients from next Monday.</p>",
        ),
        _msg(
            "SYN-LUNCH",
            base + timedelta(hours=3),
            lead,
            "Team Lead",
            "<p>Team lunch on Friday at 1? Reply here 🙂</p>",
        ),
        _msg(
            "SYN-LUNCH-R1",
            base + timedelta(hours=3, minutes=5),
            senior,
            "Senior Processor",
            "<p>I'm in.</p>",
            reply_to="SYN-LUNCH",
        ),
        _msg(
            "SYN-Q",
            base + timedelta(days=1),
            proc,
            "AP Processor",
            "<p>Can I post a courier invoice without a PO if it's small?</p>",
        ),
        _msg(
            "SYN-Q-R1",
            base + timedelta(days=1, minutes=20),
            senior,
            "Senior Processor",
            "<p>Check the non-PO list in the SOP first, I'm not sure courier is on it.</p>",
            reply_to="SYN-Q",
        ),
        _msg(
            "SYN-OOO",
            base + timedelta(days=1, hours=1),
            senior,
            "Senior Processor",
            "<p>Automatic reply: I am out of office until Monday.</p>",
        ),
        _msg(
            "SYN-REMIND",
            base + timedelta(days=2),
            lead,
            "Team Lead",
            "<p>Reminder: invoices for the payment run must be approved by 1 pm the working "
            "day before the run, as the SOP says. Late ones wait for the next run.</p>",
        ),
    ]
    return {
        "team": "AP Operations",
        "channel": "ap-questions",
        "exported": datetime(2026, 11, 14, tzinfo=UTC).isoformat(),
        "note": "Synthetic test export: real question texts from teams_questions (sampled), "
        "plus hand-written SYN-* threads. Built by scripts/make_teams_export.py.",
        "value": msgs + synthetic,
    }


def main() -> None:
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(data['value'])} messages")


if __name__ == "__main__":
    main()
