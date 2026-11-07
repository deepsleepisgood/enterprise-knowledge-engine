"""Per-format parser tests on tiny generated fixtures (TEST_PLAN level 2)."""

from __future__ import annotations

import io
from collections import Counter

import pytest

from app.ingest.blocks import Block, detect_turns
from app.ingest.detect import detect
from app.ingest.parsers import parse
from app.ingest.segment import infer_headings, segment, split_documents


def _docx(build) -> bytes:
    import docx

    d = docx.Document()
    build(d)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _locators(data: bytes, name: str = "f") -> list[str]:
    r = parse(data, detect(data, name)[0])
    return [p.locator for doc in split_documents(infer_headings(r.blocks)) for p in segment(doc)]


# ---------------------------------------------------------------- detection


@pytest.mark.parametrize(
    ("data", "name", "kind"),
    [
        (b"%PDF-1.7\n...", "x.bin", "pdf"),
        (b"WEBVTT\n\n00:00.000 --> 00:02.000\nHi", "x.txt", "vtt"),
        (b"<!doctype html><html><body><p>x</p></body></html>", "x.dat", "html"),
        (
            b"From: a@b.c\nTo: d@e.f\nSubject: s\nDate: Mon, 2 Nov 2026 10:00:00 +0530\n\nbody",
            "x",
            "eml",
        ),
        (b"# Title\n\nText", "x", "markdown"),
        (b'{"messages": []}', "x", "json"),
        (b"\x00\x01\x02binary\x00", "x.docx", "unknown"),
    ],
)
def test_detect_by_content_not_extension(data, name, kind) -> None:
    assert detect(data, name)[0] == kind


# ---------------------------------------------------------------- docx


def test_docx_with_heading_styles() -> None:
    def build(d):
        d.add_heading("1. Scope", level=1)
        d.add_paragraph("Applies to everyone.")
        d.add_heading("1.1 Leave", level=2)
        d.add_paragraph("Twelve days a year.")
        d.add_paragraph("Apply in the portal.", style="List Number")
        d.add_paragraph("Manager approves.", style="List Number")

    data = _docx(build)
    assert detect(data, "a.bin")[0] == "docx"
    locs = _locators(data)
    assert "1" in locs and "1.1" in locs


def test_docx_without_heading_styles_infers_structure_from_numbering() -> None:
    def build(d):
        for line in [
            "1. Purpose",
            "This policy explains leave.",
            "2. Entitlement",
            "Staff get twelve days.",
            "2.1 Carry forward",
            "Up to five days carry over.",
        ]:
            d.add_paragraph(line)

    locs = _locators(_docx(build))
    assert {"1", "2", "2.1"} <= set(locs)


# ---------------------------------------------------------------- pdf


def _pdf(pages: list[list[tuple[str, float, tuple[float, float]]]]) -> bytes:
    import fitz

    doc = fitz.open()
    for items in pages:
        page = doc.new_page(width=595, height=842)
        for text, size, (x, y) in items:
            page.insert_text((x, y), text, fontsize=size)
    return doc.tobytes()


def test_pdf_headings_from_font_size_and_reading_order() -> None:
    data = _pdf(
        [
            [
                ("1 Travel policy", 18, (50, 80)),
                ("Economy class for all flights under six hours.", 10, (50, 110)),
                ("2 Meals", 18, (50, 160)),
                ("Up to thirty euros per day.", 10, (50, 190)),
            ]
        ]
    )
    r = parse(data, "pdf")
    assert r.tier == 1 and r.quality > 0.5
    heads = [b.text for b in r.blocks if b.type == "heading"]
    assert heads == ["1 Travel policy", "2 Meals"]
    assert {"1", "2"} <= set(_locators(data))


def test_two_column_pdf_keeps_column_order() -> None:
    left = [(f"Left line {i} about the first topic.", 10, (40, 100 + i * 14)) for i in range(5)]
    right = [(f"Right line {i} about the second topic.", 10, (320, 100 + i * 14)) for i in range(5)]
    r = parse(_pdf([left + right]), "pdf")
    text = " ".join(b.text for b in r.blocks)
    assert text.index("Left line 4") < text.index("Right line 0")


def test_pdf_with_almost_no_text_is_low_quality_and_held() -> None:
    r = parse(_pdf([[(".", 10, (50, 50))], [(".", 10, (50, 50))]]), "pdf")
    assert r.quality < 0.5
    assert any("characters per page" in n for n in r.notes)


def test_pdf_table_becomes_table_block() -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    y = 100
    for row in [("Grade", "Days"), ("Junior", "12"), ("Senior", "18")]:
        for j, cell in enumerate(row):
            x0 = 50 + j * 150
            page.draw_rect(fitz.Rect(x0, y, x0 + 150, y + 20))
            page.insert_text((x0 + 5, y + 14), cell, fontsize=10)
        y += 20
    r = parse(doc.tobytes(), "pdf")
    tables = [b for b in r.blocks if b.type == "table"]
    assert tables and tables[0].rows[0] == ["Grade", "Days"]


# ---------------------------------------------------------------- spreadsheets, slides, html


def test_xlsx_with_several_sheets_gives_records() -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Grades"
    ws.append(["grade", "days"])
    ws.append(["junior", 12])
    ws2 = wb.create_sheet("Holidays")
    ws2.append(["date", "name"])
    ws2.append(["2026-01-26", "Republic Day"])
    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()
    assert detect(data, "x")[0] == "xlsx"
    r = parse(data, "xlsx")
    docs = split_documents(r.blocks)
    ps = [p for d in docs for p in segment(d)]
    records = [p for p in ps if p.segment_kind == "record"]
    assert {p.locator for p in records} == {"Grades row 1", "Holidays row 1"}
    assert "grade: junior; days: 12" in [p.text for p in records]


def test_pptx_slides_with_speaker_notes() -> None:
    from pptx import Presentation

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Expense claims"
    s.placeholders[1].text = "Submit within 30 days"
    s.notes_slide.notes_text_frame.text = "Late claims need director approval."
    buf = io.BytesIO()
    prs.save(buf)
    r = parse(buf.getvalue(), "pptx")
    assert r.blocks[0].type == "heading" and r.blocks[0].position["slide"] == 1
    assert any(b.meta.get("speaker_notes") for b in r.blocks)
    ps = [p for d in split_documents(r.blocks) for p in segment(d)]
    assert any("director approval" in p.text for p in ps)


def test_html_drops_navigation_boilerplate() -> None:
    html = (
        b"<html><head><title>Leave</title></head><body><nav>Home | About</nav>"
        b"<h1>Leave policy</h1><p>Twelve days.</p><ol><li>Apply</li><li>Approve</li></ol>"
        b"<footer>Copyright</footer></body></html>"
    )
    r = parse(html, "html")
    text = " ".join(b.text for b in r.blocks)
    assert "Home" not in text and "Copyright" not in text and "Twelve days." in text
    assert [b.meta.get("ordered") for b in r.blocks if b.type == "list_item"] == [True, True]


# ---------------------------------------------------------------- email, transcripts


def test_eml_strips_quoted_reply_and_signature() -> None:
    eml = (
        b"From: Finance Controller <fc@example.com>\nTo: team@example.com\n"
        b"Subject: Tolerance change\nDate: Mon, 9 Nov 2026 10:00:00 +0530\n\n"
        b"From Monday the bulk tolerance is 7%.\n\nRegards,\nPriya\nFinance Controller\n\n"
        b"On Fri, 6 Nov 2026 at 09:00, Ops <ops@example.com> wrote:\n> what is the tolerance?\n"
    )
    r = parse(eml, "eml")
    text = " ".join(b.text for b in r.blocks)
    assert "7%" in text and "what is the tolerance" not in text and "Priya" not in text
    assert r.file_meta["subject"] == "Tolerance change"
    assert r.blocks[0].type == "heading"


def test_vtt_with_speakers() -> None:
    vtt = (
        b"WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<v Asha>Welcome to onboarding.\n\n"
        b"00:01:05.000 --> 00:01:09.000\n<v Ravi>When is payroll?\n\n"
        b"00:01:10.000 --> 00:01:15.000\n<v Asha>On the last working day.\n"
    )
    r = parse(vtt, "vtt")
    turns = [b for b in r.blocks if b.type == "turn"]
    assert [(t.time, t.speaker) for t in turns] == [
        ("00:01", "Asha"),
        ("01:05", "Ravi"),
        ("01:10", "Asha"),
    ]
    ps = [p for d in split_documents(r.blocks) for p in segment(d)]
    joined = [p for p in ps if p.meta.get("question_joined")]
    assert joined and joined[0].locator == "[01:10]" and "When is payroll?" in joined[0].text


def test_timestamped_lines_become_turns_exactly() -> None:
    blocks = detect_turns(
        [
            Block("paragraph", "[04:30] Trainer: Then matching."),
            Block("list_item", "10:05 — Opens five items."),
            Block("paragraph", "Plain text."),
        ]
    )
    assert [(b.type, b.time, b.time_style, b.speaker) for b in blocks] == [
        ("turn", "04:30", "bracket", "Trainer"),
        ("turn", "10:05", "plain", None),
        ("paragraph", None, None, None),
    ]


# ---------------------------------------------------------------- unknown and long text


def test_unknown_binary_is_flagged_not_dropped() -> None:
    r = parse(b"\x00\x01\x02\x03" * 100, "unknown")
    assert r.tier == 5 and r.quality == 0.0 and r.notes


def test_legacy_office_without_libreoffice_is_flagged(monkeypatch) -> None:
    from app.ingest import parsers

    monkeypatch.setattr(parsers, "_libreoffice", lambda: None)
    r = parse(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100, "legacy_office")
    assert r.tier == 5 and "LibreOffice" in r.notes[0]


def test_unstructured_text_falls_back_to_windows() -> None:
    text = " ".join(f"word{i}" for i in range(900)).encode()
    r = parse(text, "text")
    ps = [p for d in split_documents(r.blocks) for p in segment(d)]
    assert len(ps) >= 3 and all(p.segment_kind == "window" for p in ps)
    assert Counter(p.locator for p in ps).most_common(1)[0][1] == 1
