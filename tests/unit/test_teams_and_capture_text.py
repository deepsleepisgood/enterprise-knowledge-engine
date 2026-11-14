"""Teams chat-export connector and the expert-capture transcript, without a database.

Both produce text the normal parser and segmenter must read as a chat transcript: one passage
per message (or per captured entry), with the speaker and the time as the citation locator.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from app.capture import interview as cap
from app.ingest import metadata as md
from app.ingest.connectors import from_upload, teams
from app.ingest.detect import detect
from app.ingest.parsers import parse
from app.ingest.segment import infer_headings, segment, split_documents

ROOT = Path(__file__).resolve().parents[2]


def _passages(text: str, channel: str) -> tuple[list, str]:
    data = text.encode("utf-8")
    kind, _ = detect(data, "x.md")
    docs = split_documents(infer_headings(parse(data, kind).blocks))
    assert len(docs) == 1
    m = md.infer(
        docs[0],
        filename="x.md",
        file_meta={},
        received_at=dt.datetime.now(dt.UTC),
        channel=channel,
        llm_fn=None,
    )
    return segment(docs[0]), m.get("doc_type")


def _msg(mid, at, name, html, reply=None, role=None, kind="message"):  # noqa: ANN001
    user = {"displayName": name, **({"jobTitle": role} if role else {})}
    return {
        "id": mid,
        "replyToId": reply,
        "messageType": kind,
        "createdDateTime": at,
        "from": {"user": user},
        "body": {"contentType": "html", "content": html},
    }


EXPORT = {
    "team": "AP",
    "channel": "questions",
    "value": [
        _msg(
            "1",
            "2026-11-02T09:00:00Z",
            "Kavya Menon",
            "<p>Is the <b>policy</b> still 1%?</p>",
            role="Senior Processor",
        ),
        _msg("2", "2026-11-02T09:05:00Z", "Sneha Iyer", "<p>Yes,<br>see SOP 4.2</p>", reply="1"),
        _msg("3", "2026-11-02T10:00:00Z", "System", "<p>joined</p>", kind="systemEventMessage"),
        _msg("4", "2026-11-03T08:00:00Z", "Rohan (Lead)", "<div>Lunch?</div>"),
        {
            **_msg("5", "2026-11-03T08:01:00Z", "X", "<p>gone</p>"),
            "deletedDateTime": "2026-11-03T08:02:00Z",
        },
    ],
}


def test_a_teams_export_is_recognised_and_split_into_threads() -> None:
    data = json.dumps(EXPORT).encode()
    assert teams.is_teams_export(data)
    assert not teams.is_teams_export(b'{"value": [{"a": 1}]}')
    assert not teams.is_teams_export(b"not json")
    eps = from_upload("export.json", data)
    assert [e.channel for e in eps] == ["teams", "teams"]  # system + deleted messages skipped
    first = eps[0]
    assert first.sender == "Kavya Menon" and first.sender_role == "Senior Processor"
    assert first.received_at == dt.datetime(2026, 11, 2, 9, 0, tzinfo=dt.UTC)
    assert first.filename == "export#1.md" and first.meta["teams"]["messages"] == 2
    text = first.data.decode()
    assert "# Teams thread — AP / questions" in text and "policy" not in text.split("\n")[0]
    assert "[09:05] Sneha Iyer: Yes, see SOP 4.2" in text  # one line per message, tags gone
    assert "[08:00] Rohan Lead: Lunch?" in eps[1].data.decode()  # name made turn-safe
    # Any other JSON upload stays an ordinary file.
    other = from_upload("data.json", b'{"rows": [1, 2]}')
    assert len(other) == 1 and other[0].channel == "upload"


def test_a_chat_without_replies_splits_at_long_pauses() -> None:
    msgs = [
        teams.Message(
            str(i), None, dt.datetime(2026, 11, 2, h, 0, tzinfo=dt.UTC), "A", None, "x", "c"
        )
        for i, h in enumerate([9, 10, 16, 17])
    ]
    assert [[m.id for m in t] for t in teams.threads(msgs)] == [["0", "1"], ["2", "3"]]


def test_a_thread_becomes_one_passage_per_message_with_speaker_and_time() -> None:
    eps = from_upload("export.json", json.dumps(EXPORT).encode())
    passages, doc_type = _passages(eps[0].data.decode(), "teams")
    assert doc_type == "teams"  # the channel names the type, never the message words
    (turn,) = [p for p in passages if p.segment_kind == "turn"]
    # A question joins the reply that follows (as in an interview): one passage, cited at the
    # reply's time, so the answer keeps its question as context.
    assert (turn.speaker, turn.locator) == ("Sneha Iyer", "[09:05]")
    assert "Is the policy still 1%?" in turn.text and "see SOP 4.2" in turn.text


def test_the_synthetic_export_builds_every_thread() -> None:
    path = ROOT / "synthetic" / "teams_export.json"
    eps = from_upload(path.name, path.read_bytes())
    ids = {e.meta["teams"]["thread"] for e in eps}
    assert {"SYN-TIP", "SYN-CLAIM", "SYN-LUNCH", "SYN-Q", "SYN-OOO", "SYN-REMIND"} <= ids
    tip = next(e for e in eps if e.meta["teams"]["thread"] == "SYN-TIP")
    assert tip.meta["teams"]["messages"] == 2  # the post and its reply


ENTRY = cap.Entry(
    subject="Balaji Logistics",
    habit="Re-sends a late-paid invoice with /A added to the number",
    trigger="same amount and date as an invoice already posted",
    what_to_do="check for the original before posting",
    evidence="three cases this year",
    author="asha.rao@corp",
    author_role="Senior Processor",
    date=dt.date(2026, 11, 15),
)


def test_a_captured_entry_is_one_interview_turn() -> None:
    text = cap.transcript(ENTRY, "Balaji Logistics (V20000)")
    passages, doc_type = _passages(text, cap.CHANNEL)
    assert doc_type == "interview"  # the schema's practice ranking applies
    (turn,) = [p for p in passages if p.segment_kind == "turn"]
    assert turn.speaker == "Asha rao" and turn.locator == "[00:00]"
    assert "About Balaji Logistics (V20000)" in turn.text and "How I know" in turn.text
    assert cap.statement(ENTRY, "Balaji Logistics (V20000)") == (
        "Balaji Logistics (V20000): Re-sends a late-paid invoice with /A added to the number. "
        "What to do: check for the original before posting."
    )


def test_capture_files_notes_where_the_plugin_says() -> None:
    f = cap.filing()
    assert (f.subject_type, f.attribute) == ("supplier", "supplier_habits.habit_note")
    q = cap.questions()
    assert len(q["questions"]) == 5 and q["default_reviewer"] == cap.PROCESS_OWNER
    assert cap.PROCESS_OWNER in q["reviewers"]
