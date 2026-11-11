"""Structure inference on canonical blocks (no file formats, no company templates)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.ingest.blocks import Block
from app.ingest.metadata import infer, parse_date
from app.ingest.segment import (
    heading_label,
    infer_headings,
    is_metadata_table,
    segment,
    split_documents,
    table_kv,
)


def H(text: str, level: int = 1) -> Block:
    return Block("heading", text, level=level)


def P(text: str) -> Block:
    return Block("paragraph", text)


def T(rows: list[list[str]]) -> Block:
    return Block("table", rows=rows)


def L(text: str, ordered: bool = True) -> Block:
    return Block("list_item", text, meta={"ordered": ordered})


def test_heading_labels() -> None:
    assert heading_label("4.2 Price tolerance") == ("4.2", "Price tolerance")
    assert heading_label("12. Worked examples") == ("12", "Worked examples")
    assert heading_label("Part C — Client memo X-1") == ("Part C", "Client memo X-1")
    assert heading_label("Video 1 — Onboarding basics") == ("Video 1", "Onboarding basics")
    assert heading_label("A very long heading without any numbering at all") == (
        None,
        "A very long heading without any numbering at all",
    )


def test_metadata_table_needs_known_keys() -> None:
    assert is_metadata_table(T([["Version", "2.0"], ["Effective", "1 Jan 2026"], ["Owner", "HR"]]))
    assert not is_metadata_table(T([["Role", "Responsibility"], ["Clerk", "Files papers"]]))
    # A spreadsheet's caption row above the key/value rows does not hide the header table.
    cap = T([["Document", ""], ["Version", "4.0"], ["Owner", "Ops"], ["Applies to", "A, B"]])
    assert is_metadata_table(cap) and table_kv(cap) == {
        "Version": "4.0",
        "Owner": "Ops",
        "Applies to": "A, B",
    }
    assert not is_metadata_table(T([["Up to 10 days", "Manager"], ["Above 10 days", "Director"]]))


def test_pack_of_documents_is_split_when_sections_open_with_metadata() -> None:
    blocks = [
        P("Collected memos"),
        H("Memo A — Leave for interns"),
        T([["Issued", "1 May 2026"], ["From", "HR"]]),
        P("Interns get five days."),
        H("Memo B — Leave for contractors"),
        T([["Issued", "2 May 2026"], ["From", "HR"]]),
        P("Contractors get none."),
        H("Memo C — Old FAQ"),
        T([["Question", "Answer"], ["How many days?", "Ten."]]),
    ]
    docs = split_documents(blocks)
    assert [d.label for d in docs] == ["Memo A", "Memo B", "Memo C"]
    assert docs[0].meta_kv == {"Issued": "1 May 2026", "From": "HR"}
    assert docs[2].meta_kv == {}  # a pack member without a header table is still its own doc


def test_single_document_with_header_table() -> None:
    blocks = [
        P("Leave Policy — version 2"),
        T([["Version", "2"], ["Effective", "1 Jan 2026"]]),
        H("1. Scope"),
        P("All staff."),
        H("2. Days"),
        P("Twelve."),
    ]
    (doc,) = split_documents(blocks)
    assert doc.meta_kv["Version"] == "2"
    locs = [p.locator for p in segment(doc)]
    assert locs == ["preamble", "1", "2"]


def test_ordered_steps_and_parent() -> None:
    blocks = [
        H("Part A — Posting"),
        T([["Reference", "W-1, version 1"], ["Updated", "1 May 2026"]]),
        L("Open the queue."),
        L("Check duplicates."),
        L("Post."),
        H("Part B — Other"),
        T([["Reference", "W-2"], ["Updated", "2 May 2026"]]),
        P("Short."),
    ]
    docs = split_documents(blocks)
    ps = segment(docs[0])
    assert [p.locator for p in ps] == [
        "Part A",
        "Part A, step 1",
        "Part A, step 2",
        "Part A, step 3",
    ]
    assert not ps[0].leaf and all(p.leaf and p.parent_key == ps[0].key for p in ps[1:])


def test_bullets_stay_in_their_section() -> None:
    blocks = [H("3.1 Channels"), P("Invoices arrive by:"), L("Portal", False), L("Email", False)]
    ps = segment(split_documents(blocks)[0])
    assert [p.locator for p in ps] == ["3.1"] and "- Portal" in ps[0].text


def test_large_table_split_into_rows_with_header() -> None:
    rows = [["Code", "Meaning"]] + [[f"C{i}", f"meaning {i}"] for i in range(8)]
    ps = segment(split_documents([H("10. Codes"), T(rows)])[0])
    row_ps = [p for p in ps if p.segment_kind == "table_row"]
    assert len(row_ps) == 8 and all(p.locator == "10" for p in row_ps)
    assert all(p.text.startswith("| Code | Meaning |") for p in row_ps)


def test_question_joins_answer_in_transcripts() -> None:
    blocks = [
        H("Interview 1 — A senior clerk"),
        T([["Recorded", "8 Sep 2026"], ["Interviewer", "KM"]]),
        Block(
            "turn",
            "What do new people get wrong?",
            time="00:30",
            time_style="bracket",
            speaker="Interviewer",
        ),
        Block("turn", "The tolerance.", time="00:42", time_style="bracket", speaker="Asha"),
        H("Interview 2 — Another"),
        T([["Recorded", "9 Sep 2026"], ["Interviewer", "KM"]]),
    ]
    ps = segment(split_documents(blocks)[0])
    turns = [p for p in ps if p.segment_kind == "turn"]
    assert [p.locator for p in turns] == ["Interview 1 [00:42]"]
    assert "What do new people get wrong?" in turns[0].text and turns[0].speaker == "Asha"


def test_flat_document_structure_repair_hook() -> None:
    blocks = [
        Block("paragraph", "OVERVIEW", meta={"all_caps": True}),
        P("Text one."),
        Block("paragraph", "DETAILS", meta={"all_caps": True}),
        P("Text two."),
    ]
    calls = []

    def repair(lines):
        calls.append(lines)
        return [1, 1]

    out = infer_headings(blocks, repair=repair)
    assert calls == [["OVERVIEW", "DETAILS"]]
    assert [b.type for b in out] == ["heading", "paragraph", "heading", "paragraph"]


def test_dates_and_precision() -> None:
    assert parse_date("effective 1 April 2026") == (date(2026, 4, 1), "day")
    assert parse_date("Recorded February 2026") == (date(2026, 2, 1), "month")
    assert parse_date("2026-11-16") == (date(2026, 11, 16), "day")
    assert parse_date("April 1, 2026") == (date(2026, 4, 1), "day")


def test_metadata_without_llm_has_provenance() -> None:
    blocks = [
        H("Part C — Client memo CM-X-02 (Northwind)"),
        T(
            [
                ["Subject", "Bulk tolerance"],
                ["Issued", "15 April 2026"],
                ["From", "Controller, Northwind"],
                ["Valid until", "31 March 2027"],
            ]
        ),
        P("Tolerance is 5%."),
        H("Part D — Client memo CM-Y-01"),
        T([["Issued", "2 Jan 2026"], ["From", "QA"]]),
    ]
    doc = split_documents(blocks)[0]
    m = infer(
        doc,
        filename="memos.docx",
        file_meta={},
        received_at=datetime(2026, 11, 7, tzinfo=UTC),
        channel="upload",
    )
    assert m.get("dated") == date(2026, 4, 15)
    assert m.get("valid_until") == date(2027, 3, 31)
    assert m.get("doc_type") == "memo" and m.get("short_label") == "CM-X-02"
    assert m.fields["dated"].origin.startswith("header table")
    assert m.fields["dated"].confidence >= 0.9


def test_key_value_lines_on_top_act_as_header() -> None:
    blocks = [
        P("Handbook, version 2"),
        P("Version: 2.0"),
        P("Effective: 1 April 2026"),
        P("Owner: People Team"),
        H("1. Purpose"),
        P("Note: this line is body text, not a header."),
    ]
    doc = split_documents(blocks)[0]
    m = infer(
        doc,
        filename="handbook.pdf",
        file_meta={},
        received_at=datetime(2026, 11, 8, tzinfo=UTC),
        channel="upload",
    )
    assert m.get("dated") == date(2026, 4, 1)
    assert m.get("version") == "2.0"
    assert m.get("owner") == "People Team"


def test_key_value_lines_under_the_title_act_as_header() -> None:
    blocks = [
        H("Visitor parking note"),
        P("Effective: 1 November 2026"),
        P("Owner: Facilities desk"),
        P("Visitors park in bay C only."),
        H("Badges"),
        P("Owner: reception (body text, not a header)."),
    ]
    doc = split_documents(blocks)[0]
    m = infer(
        doc,
        filename="parking.md",
        file_meta={},
        received_at=datetime(2026, 11, 8, tzinfo=UTC),
        channel="upload",
    )
    assert m.get("dated") == date(2026, 11, 1)
    assert m.get("owner") == "Facilities desk"


def test_uploaded_email_file_uses_its_date_header() -> None:
    doc = split_documents([P("Hello, from 1 January the rule changes.")])[0]
    m = infer(
        doc,
        filename="note.eml",
        file_meta={
            "from": "a@x.example",
            "subject": "Rule",
            "date": "Tue, 20 Oct 2026 09:00:00 +0000",
        },
        received_at=datetime(2026, 11, 8, tzinfo=UTC),
        channel="upload",
    )
    assert m.get("dated") == date(2026, 10, 20)


def test_small_sheet_is_one_retrievable_passage_large_sheet_is_not() -> None:
    from pathlib import Path

    from app.ingest.detect import detect
    from app.ingest.parsers import parse
    from app.ingest.segment import segment

    f = Path(__file__).resolve().parents[2] / "synthetic" / "corpus2_hr" / "leave_entitlements.xlsx"
    data = f.read_bytes()
    doc = split_documents(parse(data, detect(data, f.name)[0]).blocks)[0]
    tables = [p for p in segment(doc) if p.segment_kind == "table"]
    assert len(tables) == 1 and tables[0].leaf is True
    assert "| L4 | 30 | 10 |" in tables[0].text

    rows = [["Id", "Amount"], *[[str(i), str(i * 10)] for i in range(40)]]
    big = Block(type="table", rows=rows, meta={"spreadsheet": True}, position={"sheet": "Data"})
    big_doc = split_documents([big])[0]
    summary = [p for p in segment(big_doc) if p.segment_kind == "table"][0]
    assert summary.leaf is False and "| 39 |" not in summary.text
